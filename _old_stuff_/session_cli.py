#!/usr/bin/env python3
import argparse
import os
import sys
import tempfile
import yaml
from typing import List, Optional, Dict, Any

STEP_ORDER = ["audio", "clean", "scenes", "summarize", "assemble"]


def parse_players(value: Optional[str]) -> List[str]:
    if not value:
        return []
    # support comma or semicolon separated
    parts = [p.strip() for p in value.replace(";", ",").split(",")]
    return [p for p in parts if p]


def ensure_step_bounds(frm: str, to: str) -> None:
    if frm not in STEP_ORDER or to not in STEP_ORDER:
        raise ValueError(f"--from/--to must be one of: {', '.join(STEP_ORDER)}")
    if STEP_ORDER.index(frm) > STEP_ORDER.index(to):
        raise ValueError("--from must be <= --to in pipeline order")


def infer_transcribe_mode(audio: Optional[str], vtt: Optional[str]) -> str:
    if vtt:
        return "webvtt"
    if audio:
        return "audio"
    return "missing"


def build_temp_metadata(
    session_number: int,
    campaign: str,
    campaign_name: Optional[str],
    players: List[str],
    dm: Optional[str],
    audio: Optional[str],
    diarization: Optional[str],
    vtt: Optional[str],
    world_info_file: Optional[str],
    style_guide_file: Optional[str],
    session_date: Optional[str],
    dr: Optional[str],
    dr_end: Optional[str],
    example_files: Optional[List[str]]
) -> str:
    data = {
        "session_number": session_number,
        "campaign": campaign,
        "campaign_name": campaign_name or campaign,
        "characters": players or [],
        "dm": dm or "",
        "world_info_file": world_info_file,
        "style_guide_file": style_guide_file,
        "audio_file": audio,
        "diarization_file": diarization,
        "vtt_file": vtt,
        "session_date": session_date,
        "DR": dr,
        "DR_end": dr_end,
        "example_session_files": example_files or [],
    }
    # Write to a temp YAML (SessionNote currently requires a YAML path)
    fd, path = tempfile.mkstemp(prefix=f"session_{session_number}_", suffix=".yaml")
    os.close(fd)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)
    return path


def run_audio(note, mode: str):
    # mode is either 'webvtt' or 'audio'
    if mode == "webvtt":
        print("[audio] Using WebVTT transcript -> raw transcript")
        note.generate_final_transcript_from_vtt()
    elif mode == "audio":
        print("[audio] Using audio + diarization -> raw transcript")
        note.transcribe_session()
    else:
        raise RuntimeError("No audio or vtt provided for audio step")


def run_clean(note, skip_clean: bool):
    note.generate_transcript_filenames()
    if skip_clean:
        # Pass-through: use raw transcript as cleaned
        if not note.metadata.raw_transcript_file or not os.path.exists(note.metadata.raw_transcript_file):
            raise FileNotFoundError("Raw transcript not found; cannot --skip-clean")
        print("[clean] Skipped. Copying raw transcript -> cleaned transcript")
        with open(note.metadata.raw_transcript_file, "r") as src, open(note.metadata.cleaned_transcript_file, "w") as dst:
            dst.write(src.read())
    else:
        print("[clean] Cleaning transcript via LLM")
        note.produce_cleaned_transcript()


def run_scenes(note):
    print("[scenes] Preparing scene-marked transcript and splitting into scenes")
    note.process_transcript_into_scenes()


def run_summarize(note):
    print("[summarize] Generating per-scene summaries")
    # Replicate summary loop from execute(), but without forcing merge/assemble
    summaries = []
    for scene_file in note.metadata.scene_segments or []:
        summ = note.summarize_scene(scene_file)
        summary_path = scene_file.replace(".txt", ".summary.json")
        with open(summary_path, 'w') as f:
            import json
            json.dump(summ.dict(), f, indent=2)
        summaries.append(summary_path)
    if not summaries:
        print("[summarize] No scenes to summarize (did you run scenes step?)")
    note.metadata.scene_summary_files = summaries
    note.write_metadata()


def run_assemble(note):
    print("[assemble] Merging summaries into markdown and writing frontmatter")
    # Merge
    note.merge_summaries_to_markdown()
    # Final session-level summary and frontmatter
    note.generate_final_session_note()
    print(f"[assemble] Final session note written: {note.metadata.final_note}")


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--session-number", type=int, required=True, help="Session number (e.g., 106)")
    p.add_argument("--campaign", type=str, required=True, help="Campaign key/name used in filenames")
    p.add_argument("--campaign-name", type=str, help="Campaign display name (defaults to --campaign)")
    p.add_argument("--players", type=str, help="Comma/semicolon-separated list of players")
    p.add_argument("--dm", type=str, help="Dungeon Master name")
    p.add_argument("--profile", type=str, help="Profile name (e.g., default, fast); uses profiles/<name>.yaml")

    p.add_argument("--audio", type=str, help="Path to audio file")
    p.add_argument("--diarization", type=str, help="Path to diarization JSON (required if using --audio)")
    p.add_argument("--vtt", type=str, help="Path to WebVTT transcript")

    p.add_argument("--world-info-file", type=str, help="Path to world info terms file")
    p.add_argument("--style-guide-file", type=str, help="Path to style guide JSON for cleaning")

    p.add_argument("--session-date", type=str, help="YYYY-MM-DD (real world date)")
    p.add_argument("--dr", type=str, help="Start DR date")
    p.add_argument("--dr-end", type=str, help="End DR date")
    p.add_argument("--examples", type=str, help="Comma-separated example narrative markdown files")


def _apply_yaml_defaults(parser: argparse.ArgumentParser, subparsers: Dict[str, argparse.ArgumentParser], yaml_path: Optional[str]):
    if not yaml_path:
        return
    if not os.path.exists(yaml_path):
        print(f"[warn] --args-yaml not found: {yaml_path}", file=sys.stderr)
        return
    try:
        with open(yaml_path, "r") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[warn] Failed to read --args-yaml: {e}", file=sys.stderr)
        return

    # Normalize keys: hyphens->underscores
    def norm_key(k: str) -> str:
        return (k or "").replace("-", "_")

    # Map 'from'/'to' to parser dests; also accept 'profile' from YAML
    mapped: Dict[str, Any] = {}
    for k, v in raw.items():
        nk = norm_key(k)
        if nk == "from":
            mapped["from_step"] = v
        elif nk == "to":
            mapped["to_step"] = v
        else:
            mapped[nk] = v

    # Accept lists for players/examples or comma-separated strings
    def _normalize_listish(val):
        if val is None:
            return None
        if isinstance(val, list):
            return ", ".join(str(x) for x in val)
        return str(val)

    if "players" in mapped:
        mapped["players"] = _normalize_listish(mapped["players"])
    if "examples" in mapped:
        mapped["examples"] = _normalize_listish(mapped["examples"])

    # Apply defaults to main parser and all subparsers so CLI flags override them
    parser.set_defaults(**mapped)
    for sp in subparsers.values():
        sp.set_defaults(**mapped)


def cmd_run(args) -> int:
    # Apply profile before any steps run
    if getattr(args, "profile", None):
        os.environ["PIPELINE_PROFILE"] = args.profile

    ensure_step_bounds(args.from_step, args.to_step)

    players = parse_players(args.players)
    examples = parse_players(args.examples)  # reuse parser to split

    # Sensible failovers re: inputs
    transcribe_mode = infer_transcribe_mode(args.audio, args.vtt)
    if args.from_step == "audio":
        if transcribe_mode == "missing":
            print("[warn] --from audio requested but neither --audio nor --vtt provided.\n"
                  "       You can start from --from clean if a raw transcript already exists.", file=sys.stderr)
    if args.from_step == "audio" and args.vtt and not args.audio:
        print("[info] --from audio with --vtt provided: will use WebVTT path for transcript.")
    if args.audio and not args.diarization and not args.vtt:
        print("[info] --audio provided without --diarization; will attempt integrated diarization via OpenAI if available.")

    # Build temporary metadata YAML to satisfy SessionNote's current API
    meta_path = build_temp_metadata(
        session_number=args.session_number,
        campaign=args.campaign,
        campaign_name=args.campaign_name,
        players=players,
        dm=args.dm,
        audio=args.audio,
        diarization=args.diarization,
        vtt=args.vtt,
        world_info_file=args.world_info_file,
        style_guide_file=args.style_guide_file,
        session_date=args.session_date,
        dr=args.dr,
        dr_end=args.dr_end,
        example_files=examples,
    )

    # Import SessionNote lazily from local file to avoid shadowing by other modules
    try:
        import importlib.util, pathlib
        mod_path = pathlib.Path(__file__).with_name("generate_session_note_v2.py")
        spec = importlib.util.spec_from_file_location("taelgar_generate_session_note_v2", str(mod_path))
        if spec is None or spec.loader is None:
            raise ModuleNotFoundError("generate_session_note_v2")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[arg-type]
        SessionNote = getattr(mod, "SessionNote")
    except ModuleNotFoundError as e:
        missing = str(e).split("'")[-2] if "'" in str(e) else str(e)
        print(
            f"Error importing pipeline module due to missing dependency: {missing}.\n"
            f"Install required packages (e.g., webvtt-py, openai, pydub, pydantic) and retry.",
            file=sys.stderr,
        )
        return 2

    note = SessionNote(meta_path)

    # Determine slice of steps to run
    start_idx = STEP_ORDER.index(args.from_step)
    end_idx = STEP_ORDER.index(args.to_step)
    steps_to_run = STEP_ORDER[start_idx:end_idx+1]

    for step in steps_to_run:
        if step == "audio":
            if transcribe_mode == "missing":
                print("[audio] Skipped: no --audio/--vtt provided")
            else:
                run_audio(note, transcribe_mode)
        elif step == "clean":
            run_clean(note, skip_clean=args.skip_clean)
        elif step == "scenes":
            run_scenes(note)
        elif step == "summarize":
            run_summarize(note)
        elif step == "assemble":
            # Validate minimal metadata for frontmatter
            missing_meta = []
            if not note.metadata.campaign_name:
                missing_meta.append("campaign_name")
            if not note.metadata.session_number:
                missing_meta.append("session_number")
            if missing_meta:
                print(f"[assemble] Warning: missing metadata fields: {', '.join(missing_meta)}. Frontmatter may be incomplete.")
            run_assemble(note)
        else:
            raise RuntimeError(f"Unknown step: {step}")

    return 0


def _print_exists(label: str, path: Optional[str]):
    if not path:
        print(f"- {label}: (not set)")
        return
    print(f"- {label}: {'OK' if os.path.exists(path) else 'MISSING'} — {path}")


def cmd_validate(args) -> int:
    # Apply profile before SessionNote loads
    if getattr(args, "profile", None):
        os.environ["PIPELINE_PROFILE"] = args.profile

    players = parse_players(args.players)
    examples = parse_players(args.examples)

    meta_path = build_temp_metadata(
        session_number=args.session_number,
        campaign=args.campaign,
        campaign_name=args.campaign_name,
        players=players,
        dm=args.dm,
        audio=args.audio,
        diarization=args.diarization,
        vtt=args.vtt,
        world_info_file=args.world_info_file,
        style_guide_file=args.style_guide_file,
        session_date=args.session_date,
        dr=args.dr,
        dr_end=args.dr_end,
        example_files=examples,
    )

    try:
        import importlib.util, pathlib
        mod_path = pathlib.Path(__file__).with_name("generate_session_note_v2.py")
        spec = importlib.util.spec_from_file_location("taelgar_generate_session_note_v2", str(mod_path))
        if spec is None or spec.loader is None:
            raise ModuleNotFoundError("generate_session_note_v2")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[arg-type]
        SessionNote = getattr(mod, "SessionNote")
    except ModuleNotFoundError as e:
        missing = str(e).split("'")[-2] if "'" in str(e) else str(e)
        print(
            f"Error importing pipeline module due to missing dependency: {missing}.\n"
            f"Install required packages (e.g., webvtt-py, openai, pydub, pydantic) and retry.",
            file=sys.stderr,
        )
        return 2

    note = SessionNote(meta_path)
    # Ensure derived filenames are populated for checks
    try:
        note.generate_transcript_filenames()
    except Exception:
        pass

    status = note.compute_status()

    print("Inputs")
    _print_exists("audio", note.metadata.audio_file)
    _print_exists("diarization", note.metadata.diarization_file)
    _print_exists("vtt", note.metadata.vtt_file)
    print("")

    print("Artifacts")
    _print_exists("raw_transcript", note.metadata.raw_transcript_file)
    _print_exists("cleaned_transcript", note.metadata.cleaned_transcript_file)
    _print_exists("scene_marked_transcript", note.metadata.scene_file)

    if note.metadata.scene_segments:
        all_exist = all(os.path.exists(p) for p in note.metadata.scene_segments)
        print(f"- scene_segments: {'OK' if all_exist else 'PARTIAL/MISSING'} — {len(note.metadata.scene_segments)} file(s)")
    else:
        print("- scene_segments: (none)")

    if note.metadata.scene_summary_files:
        all_exist = all(os.path.exists(p) for p in note.metadata.scene_summary_files)
        print(f"- scene_summary_files: {'OK' if all_exist else 'PARTIAL/MISSING'} — {len(note.metadata.scene_summary_files)} file(s)")
    else:
        print("- scene_summary_files: (none)")

    _print_exists("final_note", note.metadata.final_note)

    print("")
    print("Status")
    for k in ["audio", "cleaned", "scenes", "summaries", "final_note"]:
        v = status.get(k)
        print(f"- {k}: {v}")

    # Suggested next step
    order_index = {name: i for i, name in enumerate(STEP_ORDER)}
    next_step = None
    if status.get("audio") in ("missing", "diarize", "transcribe", "webvtt") and not os.path.exists(note.metadata.raw_transcript_file or ""):
        next_step = "audio"
    elif status.get("cleaned") != "processed":
        next_step = "clean"
    elif status.get("scenes") != "processed":
        next_step = "scenes"
    elif status.get("summaries") != "processed":
        next_step = "summarize"
    else:
        next_step = "assemble"

    print("")
    print(f"Suggested next step: {next_step}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Taelgar session pipeline CLI")
    parser.add_argument("--args-yaml", dest="args_yaml", help="YAML file with default CLI arguments (flags override)")

    subparsers = parser.add_subparsers(dest="command")

    # run subcommand
    run_p = subparsers.add_parser("run", help="Run bounded steps of the pipeline")
    _add_common_args(run_p)
    run_p.add_argument("--from", dest="from_step", default="audio", choices=STEP_ORDER,
                       help="First step to run: audio|clean|scenes|summarize|assemble")
    run_p.add_argument("--to", dest="to_step", default="assemble", choices=STEP_ORDER,
                       help="Last step to run (inclusive)")
    run_p.add_argument("--skip-clean", action="store_true", help="Bypass the LLM cleaning step")
    run_p.set_defaults(func=cmd_run)

    # validate subcommand
    val_p = subparsers.add_parser("validate", help="Report which inputs/artifacts exist and pipeline status")
    _add_common_args(val_p)
    val_p.set_defaults(func=cmd_validate)

    # First pass: get args_yaml path and command without failing on missing requireds
    pre_args, _ = parser.parse_known_args(argv)
    _apply_yaml_defaults(parser, {"run": run_p, "validate": val_p}, getattr(pre_args, "args_yaml", None))

    # Full parse with defaults applied
    args = parser.parse_args(argv)

    # Default command to 'run' if omitted for backward compatibility
    if not args.command:
        args.command = "run"
        args.func = cmd_run

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

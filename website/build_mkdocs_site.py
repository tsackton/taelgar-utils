import subprocess
import time
import platform
import psutil
import json
from pathlib import Path
import shutil

configfile = "autobuild.json"
with open((configfile), 'r', 2048, "utf-8") as f:
    data = json.load(f)
    obs_json_path = data.get("obsidian_template_config", 'taelgar-utils/website/obsidian-template-config.json')
    vault_id = data.get("obsidian_vault_id", None)
    vault_root_path = data.get("obsidian_vault_root", "taelgar")
    export_script = data.get("export_script", 'taelgar-utils/export_vault.py')

target_data_path = Path(vault_root_path, '.obsidian', 'plugins', 'templater-obsidian', 'data.json')  # Replace with the target path
backup_data_path = target_data_path.parent / (target_data_path.name + '.bak')
shutil.copy(target_data_path, backup_data_path)
shutil.copy(obs_json_path, target_data_path)

if vault_id is None:
    raise ValueError("Vault ID not set in config file")

url_or_file_to_open = 'obsidian://open?vault=' + vault_id
if platform.system() == 'Darwin':  # Checking if the system is macOS
    subprocess.Popen(['open', url_or_file_to_open])
    obs_proc_name = "obsidian"
else:
    subprocess.Popen(['start', '', url_or_file_to_open], shell=True)
    obs_proc_name = "obsidian.exe"

#give obisidian time to start
time.sleep(10)

# Step 2: Wait for the default application to exit
while True:
    running_processes = [p.name().lower() for p in psutil.process_iter(['name'])]
    try:
        # Check if the process is still running
        if not any(proc == obs_proc_name for proc in running_processes):
            break
        else:
            time.sleep(1)  # Wait for 1 second before checking again
    except KeyboardInterrupt:
        # Handle keyboard interrupt (Ctrl+C) to exit the script
        break

# Step 3: Run another Python script (export_vault.py)
subprocess.run(['python', export_script])

# restore original templater config
shutil.move(backup_data_path,target_data_path)
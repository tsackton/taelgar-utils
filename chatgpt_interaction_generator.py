## DOES NOT WORK ##
## PRELIMINARY TESTING CODE FROM OPENAI PLAYGROUND ##

from openai import OpenAI
client = OpenAI()

response = client.chat.completions.create(
  model="gpt-4-1106-preview",
  messages=[
    {
      "role": "system",
      "content": "You are a text parser that will output JSON. You will receive text in the format {person} {context}. You will interpret the text in the context block to generate an output that summarizes the interaction with the person. This should be the form of 1-5 words that can be inserted into a sentence with {person} as the object, so for example in a sentence like: The Dunmar Fellowship {interaction} {person}. The JSON you output will contain just the key interaction with a value equal to your summary. You will ignore brackets ([]) in the input text. You will strive to identify the most important and exciting interaction involving the person in the context, and focus on that. Please prefer a simple, one word answer, such as \"met\", if it would make sense in context."
    },
    {
      "role": "user",
      "content": "{Kisa} {Speaker [[Candrosa]], the leader of the [[Shakun Mystai]], and Elder [[Kisa]], leader of [[Karawa]], arrive and discuss the attacks -- these are the latest and most dangerous in a string of mysterious attacks. [[Kisa]] asks [[Delwath]] to investigate the problem, and he gets everyone else to help.}"
    },
    {
      "role": "assistant",
      "content": "{\"interaction\": \"investigated attacks for\"}"
    },
    {
      "role": "user",
      "content": "{Candrosa} {Speaker [[Candrosa]], the leader of the [[Shakun Mystai]], and Elder [[Kisa]], leader of [[Karawa]], arrive and discuss the attacks -- these are the latest and most dangerous in a string of mysterious attacks. [[Kisa]] asks [[Delwath]] to investigate the problem, and he gets everyone else to help.}"
    },
    {
      "role": "assistant",
      "content": "{\"interaction\": \"discussed dangers with\"}"
    },
    {
      "role": "user",
      "content": "{Alesh} {On the road, the party ran into [[Alesh]], a Dunmari scout returning from the [[Gomat]] oasis, where she had spent the night with [[Akan]] and his family, who were grazing their herds in the area. They discussed the attacks on the town, and [[Alesh]] talked about how in her childhood people were scared, but for the past decade the [[Nashtkar]], the blasted plains, had seemed, if not safe, at least less of a constant threat to [[Karawa]]. But perhaps that was changing. She rode on for the grazing lands north of [[Karawa]].}"
    },
    {
      "role": "assistant",
      "content": "{\"interaction\": \"conversed with\"}"
    }
  ],
  temperature=1,
  max_tokens=256,
  top_p=1,
  frequency_penalty=0,
  presence_penalty=0
)
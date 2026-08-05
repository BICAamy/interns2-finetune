import json
from dotenv import find_dotenv, load_dotenv

from langchain.chains.llm import LLMChain
from langchain.prompts import PromptTemplate

from LLMs.langchain_openai_compatible import OpenAICompatibleLLM

from prompt.planner_prompt import (
    PLANNER_PROMPT,
)

from data_utils import construct_instrs

load_dotenv(find_dotenv(usecwd=True), override=False)
llm = OpenAICompatibleLLM.from_env(temperature=0.0)

plan_prompt = PromptTemplate(
    template=PLANNER_PROMPT,
    input_variables=["instruction"],
)

plan_chain = LLMChain(llm=llm, prompt=plan_prompt)


splits = ['val_72']
anno_dir = '../datasets/R2R/annotations'
dataset = 'R2R'
data = construct_instrs(anno_dir, dataset, splits)

for i, sample in enumerate(data):
    print(f"Sample {i}:")
    print(sample['instruction'])
    action_plan = plan_chain.run(sample['instruction'])
    print(action_plan)
    data[i]['action_plan'] = action_plan

with open('../datasets/R2R/annotations/R2R_val_72_action_plan.json', 'w') as f:
    json.dump(data, f, indent=2)

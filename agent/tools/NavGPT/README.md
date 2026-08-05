<div align="center">

<h1>🎇NavGPT: Explicit Reasoning in Vision-and-Language Navigation with Large Language Models</h1>

<div>
    <a href='https://github.com/GengzeZhou' target='_blank'>Gengze Zhou<sup>🍕</sup></a>;
    <a href='http://www.yiconghong.me' target='_blank'>Yicong Hong<sup>🌭</sup></a>;
    <a href='http://www.qi-wu.me' target='_blank'>Qi Wu<sup>🍕</sup></a>
</div>
<sup>🍕</sup>Australian Institude for Machine Learning, The University of Adelaide <sup>🌭</sup>The Australian National University

<br>

<div>
    <a href='https://github.com/GengzeZhou/NavGPT' target='_blank'><img alt="Static Badge" src="https://img.shields.io/badge/NavGPT-v0.1-blue"></a>
    <a href='https://arxiv.org/abs/2305.16986' target='_blank'><img src='https://img.shields.io/badge/Paper-Arxiv-red'></a>
    <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
    <a href="https://github.com/langchain-ai/langchain"><img alt="Static Badge" src="https://img.shields.io/badge/🦜️🔗-Langchain-green"></a>
</div>

</div>


## 🍹 Abstract
 Trained with an unprecedented scale of data, large language models (LLMs) like ChatGPT and GPT-4 exhibit the emergence of significant reasoning abilities from model scaling. Such a trend underscored the potential of training LLMs with unlimited language data, advancing the development of a universal embodied agent. 
 In this work, we introduce the NavGPT, a purely LLM-based instruction-following navigation agent, to reveal the reasoning capability of GPT models in complex embodied scenes by performing zero-shot sequential action prediction for vision-and-language navigation (VLN).
 At each step, NavGPT takes the textual descriptions of visual observations, navigation history, and future explorable directions as inputs to reason the agent's current status, and makes the decision to approach the target.
 Through comprehensive experiments, we demonstrate NavGPT can explicitly perform high-level planning for navigation, including decomposing instruction into sub-goal, integrating commonsense knowledge relevant to navigation task resolution, identifying landmarks from observed scenes, tracking navigation progress, and adapting to exceptions with plan adjustment. 
 Furthermore, we show that LLMs is capable of generating high-quality navigational instructions from observations and actions along a path, as well as drawing accurate top-down metric trajectory given the agent's navigation history. Despite the performance of using NavGPT to zero-shot R2R tasks still falling short of trained models, we suggest adapting multi-modality inputs for LLMs to use as visual navigation agents and applying the explicit reasoning of LLMs to benefit learning-based models.

## 🍸 Method
![](assets/NavGPT.png)

## 🍻 TODOs

- [x] Release 🎇NavGPT code.
- [x] Data preprocessing code.
- [x] Custuomized LLM inference guidance.

## 🧋 Prerequisites

### 🍭 Installation

Create a conda environment and install all dependencies:

```bash
conda create --name NavGPT python=3.9
conda activate NavGPT
pip install -r requirements.txt
```

### 🍬 Data Preparation

Download R2R data from [Dropbox](https://www.dropbox.com/sh/i8ng3iq5kpa68nu/AAB53bvCFY_ihYx1mkLlOB-ea?dl=1). Put the data in `datasets` directory.

Related data preprocessing code can be found in `nav_src/scripts`.

### 🍫 DeepSeek / OpenAI-compatible API

This repository variant uses the current OpenAI Python SDK against a configurable
OpenAI-compatible Chat Completions endpoint. Copy the project-level environment
template and fill in the values supplied by your provider:

```bash
cd ../../../
cp .env.example .env
```

```dotenv
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=your-test-key
DEEPSEEK_MODEL=your-model-name
```

The original R2R runner, observation summarizer, action planner, and standalone
NavGPT tool all share these settings. `DEEPSEEK_MODEL` is intentionally
configurable because compatible gateways often expose a provider-specific model
name.

To verify the URL and key without downloading R2R data or loading InternS2:

```bash
cd ../../../
python3 -m agent.tools.NavGPT.nav_src.nav_tool_cli \
  --instruction "Move toward the exit" \
  --observation "An open doorway is visible ahead" \
  --candidates-json '[]'
```

## 🍷 R2R Navigation

### 🍴 Reproduce Validation Results

To run R2R validation with the configured DeepSeek-compatible model:
```bash
cd nav_src
python NavGPT.py --llm_provider deepseek \
    --llm_model_name "$DEEPSEEK_MODEL" \
    --llm_base_url "$DEEPSEEK_BASE_URL" \
    --output_dir ../datasets/R2R/exprs/deepseek-val-unseen \
    --val_env_name R2R_val_unseen_instr
```

Results will be saved in `datasets/R2R/exprs/deepseek-val-unseen` directory.

The default `--llm_model_name` is read from `DEEPSEEK_MODEL`.

To try NavGPT on only the first 10 samples:
```bash
cd nav_src
python NavGPT.py --llm_provider deepseek \
    --llm_model_name "$DEEPSEEK_MODEL" \
    --llm_base_url "$DEEPSEEK_BASE_URL" \
    --output_dir ../datasets/R2R/exprs/deepseek-test \
    --val_env_name R2R_val_unseen_instr \
    --iters 10
```

### 🥢 Set up Custom LLMs for 🎇NavGPT
Add your own model repo as a submodule under `nav_src/LLMs/`:
```bash
cd nav_src/LLMs
git submodule add {Your_Model_Repo}
```
or just copy your local inference code under `nav_src/LLMs/`.

Follow the [instructions](nav_src/LLMs/Add_Custom_Models.md) to set up your own LLMs for 🎇NavGPT.

Run 🎇NavGPT with your custom LLM:
```bash
cd nav_src
python NavGPT.py --llm_model_name your_custom_llm \
    --output_dir ../datasets/R2R/exprs/your_custom_llm-test
```

## 🧃 Citation
If 🎇`NavGPT` has been beneficial to your research and work, please cite our work using the following format:
```
@article{zhou2023navgpt,
  title={NavGPT: Explicit Reasoning in Vision-and-Language Navigation with Large Language Models},
  author={Zhou, Gengze and Hong, Yicong and Wu, Qi},
  journal={arXiv preprint arXiv:2305.16986},
  year={2023}
}
```

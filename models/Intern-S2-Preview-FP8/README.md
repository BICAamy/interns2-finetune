---
library_name: transformers
license: apache-2.0
license_link: https://huggingface.co/internlm/Intern-S2-Preview-FP8/blob/main/LICENSE
pipeline_tag: image-text-to-text
base_model:
- internlm/Intern-S2-Preview
---

## Intern-S2-Preview-FP8

<div align="center">
<img src="./figs/title.png" />

  <div>&nbsp;</div>

[💻Github Repo](https://github.com/InternLM/Intern-S1) • [🤗Model Collections](https://huggingface.co/collections/internlm/intern-s2) • [💬Online Chat](https://chat.intern-ai.org.cn/)


</div>

<p align="center">
    👋 join us on <a href="https://discord.gg/xa29JuW87d" target="_blank">Discord</a> and <a href="https://cdn.vansin.top/intern-s1.jpg" target="_blank">WeChat</a>
</p>



## Introduction

We introduce **Intern-S2-Preview**, an efficient 35B scientific multimodal foundation model. Beyond conventional parameter and data scaling, Intern-S2-Preview explores **task scaling**: increasing the difficulty, diversity, and coverage of scientific tasks to further unlock model capabilities. 

By extending professional scientific tasks into a full-chain training pipeline from pre-training to reinforcement learning, Intern-S2-Preview achieves performance comparable to the trillion-scale Intern-S1-Pro on multiple core professional scientific tasks, while using only 35B parameters (continued pretrained from Qwen3.5). At the same time, it maintains strong general reasoning, multimodal understanding, and agent capabilities.

### Features

- **Scientific task scaling with full-chain training.** Intern-S2-Preview scales hundreds of professional scientific tasks from pre-training to RL, enabling strong performance across multiple specialized domains at only 35B parameters. It further strengthens spatial modeling for small-molecule structures and introduces real-valued prediction modules, making it the first open-source model with both material crystal structure generation capability and strong general capabilities. 

- **Enhanced agent capabilities for scientific workflows.** Intern-S2-Preview significantly improves agentic abilities over the previous generation, achieving strong results on multiple scientific agent benchmarks.

- **Efficient RL reasoning with MTP and CoT compression.** During RL, Intern-S2-Preview adopts shared-weight MTP with KL loss to reduce the mismatch between training and inference behavior, substantially improving MTP accept rate and token generation speed. It also introduces CoT compression techniques to shorten responses while preserving strong reasoning capability, achieving improvements in both performance and efficiency. 

- **Upgraded time-series Modeling** for better physical signal representation; supports long, heterogeneous time-series (10^0–10^6 points).
<figure>
  <img src="./figs/efficiency.jpg" alt="efficient RL reasoning with MTP and CoT compression">
  <figcaption>Fig1: Reasoning Efficiency on Complex Math Benchmarks. Accuracy vs. Average Response Length. Intern-S2-Preview (red star) significantly outperforms trillion-scale Intern-S1-Pro (red circle), and achieving higher accuracy with better token efficiency among medium-size models.</figcaption>
</figure>

### Performance

We evaluate the Intern-S2-Preview on various benchmarks, including general datasets and scientific datasets. We report the performance comparison with the recent VLMs and LLMs below. 

![performance](./figs/performance.png)


> **Note**: <u>Underline</u> means the best performance among open-sourced models, **Bold** indicates the best performance among all models.

We use the [OpenCompass](https://github.com/open-compass/OpenCompass/) and [VLMEvalKit](https://github.com/open-compass/vlmevalkit) to evaluate all models. For text reasoning benchmarks, Intern-S2-Preview is evaluated with a maximum inference length of 128K tokens, while for multimodal benchmarks, it is evaluated with a maximum inference length of 64K tokens.


## Quick Start

### Sampling Parameters

We recommend using the following hyperparameters to ensure better results

```python
top_p = 0.95
top_k = 50
min_p = 0.0
temperature = 0.8
```

### Serving

Intern-S2-Preview can be deployed using any of the following LLM inference frameworks:

- LMDeploy
- vLLM
- SGLang

Detailed deployment examples for these frameworks are available in the [Model Deployment Guide](./deployment_guide.md).


## Advanced Usage

### Tool Calling

Tool Calling lets the model extend its capabilities by invoking external tools and APIs. The example below shows how to use it to fetch the latest weather forecast via an OpenAI-compatible API (based on lmdeploy api server).

```python      
      

from openai import OpenAI
import json


def get_current_temperature(location: str, unit: str = "celsius"):
    """Get current temperature at a location.

    Args:
        location: The location to get the temperature for, in the format "City, State, Country".
        unit: The unit to return the temperature in. Defaults to "celsius". (choices: ["celsius", "fahrenheit"])

    Returns:
        the temperature, the location, and the unit in a dict
    """
    return {
        "temperature": 26.1,
        "location": location,
        "unit": unit,
    }


def get_temperature_date(location: str, date: str, unit: str = "celsius"):
    """Get temperature at a location and date.

    Args:
        location: The location to get the temperature for, in the format "City, State, Country".
        date: The date to get the temperature for, in the format "Year-Month-Day".
        unit: The unit to return the temperature in. Defaults to "celsius". (choices: ["celsius", "fahrenheit"])

    Returns:
        the temperature, the location, the date and the unit in a dict
    """
    return {
        "temperature": 25.9,
        "location": location,
        "date": date,
        "unit": unit,
    }

def get_function_by_name(name):
    if name == "get_current_temperature":
        return get_current_temperature
    if name == "get_temperature_date":
        return get_temperature_date

tools = [{
    'type': 'function',
    'function': {
        'name': 'get_current_temperature',
        'description': 'Get current temperature at a location.',
        'parameters': {
            'type': 'object',
            'properties': {
                'location': {
                    'type': 'string',
                    'description': 'The location to get the temperature for, in the format \'City, State, Country\'.'
                },
                'unit': {
                    'type': 'string',
                    'enum': [
                        'celsius',
                        'fahrenheit'
                    ],
                    'description': 'The unit to return the temperature in. Defaults to \'celsius\'.'
                }
            },
            'required': [
                'location'
            ]
        }
    }
}, {
    'type': 'function',
    'function': {
        'name': 'get_temperature_date',
        'description': 'Get temperature at a location and date.',
        'parameters': {
            'type': 'object',
            'properties': {
                'location': {
                    'type': 'string',
                    'description': 'The location to get the temperature for, in the format \'City, State, Country\'.'
                },
                'date': {
                    'type': 'string',
                    'description': 'The date to get the temperature for, in the format \'Year-Month-Day\'.'
                },
                'unit': {
                    'type': 'string',
                    'enum': [
                        'celsius',
                        'fahrenheit'
                    ],
                    'description': 'The unit to return the temperature in. Defaults to \'celsius\'.'
                }
            },
            'required': [
                'location',
                'date'
            ]
        }
    }
}]



messages = [
    {'role': 'user', 'content': 'Today is 2024-11-14, What\'s the temperature in San Francisco now? How about tomorrow?'}
]

openai_api_key = "EMPTY"
openai_api_base = "http://0.0.0.0:23333/v1"
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)
model_name = client.models.list().data[0].id
response = client.chat.completions.create(
    model=model_name,
    messages=messages,
    max_tokens=32768,
    temperature=0.8,
    top_p=0.95,
    extra_body=dict(spaces_between_special_tokens=False),
    tools=tools)
print(response.choices[0].message)
messages.append(response.choices[0].message)

for tool_call in response.choices[0].message.tool_calls:
    tool_call_args = json.loads(tool_call.function.arguments)
    tool_call_result = get_function_by_name(tool_call.function.name)(**tool_call_args)
    tool_call_result = json.dumps(tool_call_result, ensure_ascii=False)
    messages.append({
        'role': 'tool',
        'name': tool_call.function.name,
        'content': tool_call_result,
        'tool_call_id': tool_call.id
    })

response = client.chat.completions.create(
    model=model_name,
    messages=messages,
    temperature=0.8,
    top_p=0.95,
    extra_body=dict(spaces_between_special_tokens=False),
    tools=tools)
print(response.choices[0].message)
```

### Switching Between Thinking and Non-Thinking Modes

Intern-S2-Preview enables thinking mode by default, enhancing the model's reasoning capabilities to generate higher-quality responses. This feature can be disabled by setting `enable_thinking=False` in `tokenizer.apply_chat_template`

```python
text = tokenizer.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True,
    enable_thinking=False  # think mode indicator
)
```

When serving Intern-S2-Preview models, you can dynamically control the thinking mode by adjusting the `enable_thinking` parameter in your requests.

```python
from openai import OpenAI
import json

messages = [
{
    'role': 'user',
    'content': 'who are you'
}, {
    'role': 'assistant',
    'content': 'I am an AI'
}, {
    'role': 'user',
    'content': 'AGI is?'
}]

openai_api_key = "EMPTY"
openai_api_base = "http://0.0.0.0:23333/v1"
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)
model_name = client.models.list().data[0].id

response = client.chat.completions.create(
    model=model_name,
    messages=messages,
    temperature=0.8,
    top_p=0.95,
    max_tokens=2048,
    extra_body={
        "chat_template_kwargs": {"enable_thinking": False}
    }
)
print(json.dumps(response.model_dump(), indent=2, ensure_ascii=False))
```

> Note: We do not recommend disabling thinking mode for agentic tasks.


### Time Series Demo

Time series inference is currently only supported in LMDeploy. To get started, download and deploy Intern-S2-Preview-FP8 with LMDeploy by following the [Model Deployment Guide](./deployment_guide.md).
Below is an example of detecting earthquake events from a time series signal file. Additional data types and functionalities are also supported.

**Please note**: this demo is slightly different from the one in [Intern-S1-Pro](https://huggingface.co/internlm/Intern-S1-Pro#time-series-demo). The main difference is that in the messages content, you need to provide time_series_url first, followed by the text prompt. Please adapt your implementation based on this demo.
```
from openai import OpenAI
from lmdeploy.vl.utils import encode_time_series_base64

openai_api_key = "EMPTY"
openai_api_base = "http://0.0.0.0:8000/v1"
client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)
model_name = client.models.list().data[0].id


def send_base64(file_path: str, sampling_rate: int = 100):
    """base64-encoded time-series data."""

    # encode_time_series_base64 accepts local file paths and http urls,
    # encoding time-series data (.npy, .csv, .wav, .mp3, .flac, etc.) into base64 strings.
    base64_ts = encode_time_series_base64(file_path)

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "time_series_url",
                    "time_series_url": {
                        "url": f"data:time_series/npy;base64,{base64_ts}",
                        "sampling_rate": sampling_rate
                    },
                },
                {
                    "type": "text",
                    "text": "Please determine whether an Earthquake event has occurred in the provided time-series data. If so, please specify the starting time point indices of the P-wave and S-wave in the event."
                },
            ],
        }
    ]

    return client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0,
        max_tokens=200,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False}
        }
    )


def send_http_url(url: str, sampling_rate: int = 100):
    """http(s) url pointing to the time-series data."""
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "time_series_url",
                    "time_series_url": {
                        "url": url,
                        "sampling_rate": sampling_rate
                    },
                },
                {
                    "type": "text",
                    "text": "Please determine whether an Earthquake event has occurred in the provided time-series data. If so, please specify the starting time point indices of the P-wave and S-wave in the event."
                },
            ],
        }
    ]

    return client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0,
        max_tokens=200,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False}
        }
    )


def send_file_url(file_path: str, sampling_rate: int = 100):
    """file url pointing to the time-series data."""
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "time_series_url",
                    "time_series_url": {
                        "url": f"file://{file_path}",
                        "sampling_rate": sampling_rate
                    },
                },
                {
                    "type": "text",
                    "text": "Please determine whether an Earthquake event has occurred in the provided time-series data. If so, please specify the starting time point indices of the P-wave and S-wave in the event."
                },
            ],
        }
    ]

    return client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0,
        max_tokens=200,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": False}
        }
    )

response = send_base64("./0092638_seism.npy")
# response = send_http_url("https://huggingface.co/internlm/Intern-S1-Pro/raw/main/0092638_seism.npy")
# response = send_file_url("./0092638_seism.npy")

print(response.choices[0].message)
```

## Agent Integration

Intern-S2-Preview can be plugged into agent frameworks in two ways: connecting to a **self-hosted deployment**, or calling the **official InternLM API**. Below we cover both, with examples for agent frameworks (OpenClaw, Hermes, etc.) and for Claude Code.

### 1. Self-hosted Deployment (LMDeploy as an example)

First, serve the model with LMDeploy following the [Model Deployment Guide](./deployment_guide.md). The example below assumes the server is running at `http://0.0.0.0:23333`.

#### Connecting Agent Frameworks

Most agent frameworks (OpenClaw, Hermes, etc.) accept an OpenAI-compatible endpoint. Point them at the LMDeploy server base url `http://0.0.0.0:23333/v1`. 

You can check the connection with the following command:

```bash
curl http://0.0.0.0:23333/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer EMPTY" \
  -d '{
    "model": "internlm/Intern-S2-Preview",
    "messages": [
      {"role": "user", "content": "Hello"}
    ],
    "temperature": 0.8,
    "top_p": 0.95
  }'
```

Or you can configure your agent framework with the environment variables

```bash
export OPENAI_API_KEY=EMPTY
export OPENAI_BASE_URL=http://0.0.0.0:23333/v1
export OPENAI_MODEL=internlm/Intern-S2-Preview
```

Remember to launch LMDeploy with `--tool-call-parser interns2-preview` so tool calls are parsed correctly.

#### Connecting Claude Code

LMDeploy exposes an Anthropic-compatible `/v1/messages` endpoint that Claude Code can talk to directly. Add the following to `~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:23333",
    "ANTHROPIC_AUTH_TOKEN": "dummy",
    "ANTHROPIC_MODEL": "internlm/Intern-S2-Preview",
    "ANTHROPIC_CUSTOM_MODEL_OPTION": "internlm/Intern-S2-Preview"
  }
}
```

For a full walkthrough (curl verification, model routing, troubleshooting), see [LMDeploy × Claude Code](https://lmdeploy.readthedocs.io/en/latest/intergration/claude_code.html).

### 2. Official Intern API

If you do not want to self-host, you can use the official Intern API. Register at [internlm.intern-ai.org.cn](https://internlm.intern-ai.org.cn/) and create an API token (`sk-xxxxxxxx`).

#### Connecting Agent Frameworks

The service is OpenAI-compatible, so any agent framework works. You can set the base url to `https://chat.intern-ai.org.cn/api/v1` and the model name to `intern-s2-preview` in the cli or config file.

You can check the connection with the following command:

```bash
curl https://chat.intern-ai.org.cn/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-xxxxxxxx" \
  -d '{
    "model": "intern-s2-preview",
    "messages": [
      {"role": "user", "content": "Hello"}
    ],
    "temperature": 0.8,
    "top_p": 0.95
  }'
```

Refer to the [Intern API documentation](https://internlm.intern-ai.org.cn/api/document?lang=en) for the current endpoint, available model names, rate limits, and advanced parameters.

#### Connecting Claude Code

Claude Code can route to the official Intern API by pointing `ANTHROPIC_BASE_URL` at the Intern Anthropic-compatible gateway:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://chat.intern-ai.org.cn",
    "ANTHROPIC_AUTH_TOKEN": "your-api-token",
    "ANTHROPIC_MODEL": "intern-s2-preview",
    "ANTHROPIC_SMALL_FAST_MODEL": "intern-s2-preview"
  }
}
```

Then start claude code with the following command:

```bash
claude --model intern-s2-preview
```

For step-by-step setup, see [Intern API × Claude Code Integration](https://internlm.intern-ai.org.cn/docEn/docs/Claude-Code-Integration).

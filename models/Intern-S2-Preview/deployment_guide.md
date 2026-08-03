# Intern-S2-Preview Deployment Guide

The Intern-S2-Preview release is a 35B-A3B model stored in bfloat16 weight format. This guide provides deployment examples for the following configurations:

- MTP speculative decoding (Recommended)
- Basic serving without MTP
- Long-context inference with YaRN RoPE configuration

> NOTE: The commands below are reference configurations. Inference frameworks are under active development, so use the latest framework documentation and your local validation results when tuning production deployments.

## LMDeploy

Use the latest LMDeploy (>=0.13.0) with Intern-S2-Preview support.

- Serving With MTP (Recommended)

```bash
lmdeploy serve api_server \
    internlm/Intern-S2-Preview \
    --trust-remote-code \
    --backend pytorch \
    --tp 2 \
    --reasoning-parser default \
    --tool-call-parser interns2-preview \
    --speculative-algorithm qwen3_5_mtp \
    --speculative-num-draft-tokens 4 \
    --max-batch-size 256
```

- Basic Serving Without MTP

```bash
lmdeploy serve api_server \
    internlm/Intern-S2-Preview \
    --trust-remote-code \
    --backend pytorch \
    --tp 2 \
    --reasoning-parser default \
    --tool-call-parser interns2-preview
```

- Long-Context Serving

For long-context inference, configure both `--session-len` and YaRN RoPE parameters. The following example uses a 512k context length:

```bash
lmdeploy serve api_server \
    internlm/Intern-S2-Preview \
    --trust-remote-code \
    --tp 2 \
    --backend pytorch \
    --reasoning-parser default \
    --tool-call-parser interns2-preview \
    --session-len 512000 \
    --max-batch-size 64 \
    --hf-overrides '{"text_config": {"rope_parameters": {"mrope_interleaved": true, "mrope_section": [11, 11, 10], "rope_type": "yarn", "rope_theta": 10000000, "partial_rotary_factor": 0.25, "factor": 4.0, "original_max_position_embeddings": 262144}}}'
```

## vLLM

Use the latest vLLM Docker image or source build with Intern-S2-Preview support.

For example, you can use the vLLM nightly Docker image `docker pull vllm/vllm-openai:cu129-nightly-a6682d1d259cca69a9ae737ea5608fbbe7520031`

- Serving With MTP (Recommended)

```bash
vllm serve internlm/Intern-S2-Preview \
    --trust-remote-code \
    --tensor-parallel-size 2 \
    --reasoning-parser qwen3 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --speculative-config '{"method":"mtp","num_speculative_tokens":4}'
```

- Basic Serving Without MTP

```bash
vllm serve internlm/Intern-S2-Preview \
    --trust-remote-code \
    --tensor-parallel-size 2 \
    --reasoning-parser qwen3 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder
```

## SGLang

Use the latest SGLang Docker image or source build with Intern-S2-Preview support.

For example, you can use the SGLang nightly Docker image `docker pull lmsysorg/sglang:nightly-dev-cu12-20260520-425dffbd`

- Serving With MTP (Recommended)

```bash
SGLANG_ENABLE_SPEC_V2=1 \
python3 -m sglang.launch_server \
  --model-path internLM/Intern-S2-Preview \
  --trust-remote-code \
  --tp-size 2 \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_coder \
  --mamba-scheduler-strategy extra_buffer \
  --speculative-algo 'NEXTN' \
  --speculative-eagle-topk 1 \
  --speculative-num-steps 3 \
  --speculative-num-draft-tokens 4
```

- Basic Serving Without MTP

```bash
python3 -m sglang.launch_server \
    --model-path internlm/Intern-S2-Preview \
    --trust-remote-code \
    --tp-size 2 \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_coder
```

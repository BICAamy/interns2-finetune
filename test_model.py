from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_path = "models/Intern-S2-Preview-FP8"

print("正在加载 tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

print("正在加载模型...")
model = AutoModelForCausalLM.from_pretrained(
    model_path,
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True
)

print("\n✅ 模型加载成功！")
print(f"总参数量: {sum(p.numel() for p in model.parameters()) / 1e9:.2f}B")
print(f"显存占用: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

# 简单测试
print("\n正在测试对话...")
response, history = model.chat(tokenizer, "你好，请简单介绍一下你自己", history=[])
print("回答:", response)

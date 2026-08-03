from pathlib import Path

import torch
import lmdeploy
from lmdeploy import GenerationConfig, PytorchEngineConfig, pipeline


# 标准 BF16 模型在容器中的实际路径
MODEL_PATH = Path(
    "/home/xl/interns2-finetune/models/Intern-S2-Preview"
)


def check_environment() -> None:
    """检查模型目录、LMDeploy 与 CUDA 环境。"""

    print("=" * 70)
    print("Intern-S2-Preview 标准 BF16 模型推理测试")
    print("=" * 70)

    print("模型目录:", MODEL_PATH)
    print("LMDeploy版本:", getattr(lmdeploy, "__version__", "unknown"))
    print("PyTorch版本:", torch.__version__)
    print("CUDA可用:", torch.cuda.is_available())
    print("可见GPU数量:", torch.cuda.device_count())

    if not MODEL_PATH.is_dir():
        raise FileNotFoundError(f"找不到模型目录：{MODEL_PATH}")

    config_file = MODEL_PATH / "config.json"
    index_file = MODEL_PATH / "model.safetensors.index.json"

    if not config_file.is_file():
        raise FileNotFoundError(f"缺少文件：{config_file}")

    if not index_file.is_file():
        raise FileNotFoundError(f"缺少文件：{index_file}")

    shards = sorted(MODEL_PATH.glob("model-*.safetensors"))
    print("发现权重分片数量:", len(shards))

    if len(shards) != 23:
        raise RuntimeError(
            f"标准模型应当有23个权重分片，当前发现{len(shards)}个。"
        )

    if not torch.cuda.is_available():
        raise RuntimeError("当前容器无法使用CUDA。")

    if torch.cuda.device_count() < 2:
        raise RuntimeError(
            "当前脚本设置tp=2，因此容器内至少需要两张可见GPU。"
        )

    for index in range(torch.cuda.device_count()):
        print(
            f"GPU {index}:",
            torch.cuda.get_device_name(index),
            "Compute Capability:",
            torch.cuda.get_device_capability(index),
        )


def main() -> None:
    check_environment()

    # LMDeploy PyTorch推理后端配置
    backend_config = PytorchEngineConfig(
        # 两张GPU进行张量并行
        tp=2,

        # 标准模型的权重类型是BF16
        dtype="bfloat16",

        # 测试阶段只使用4K上下文，减少KV Cache占用
        session_len=4096,

        # 使用40%的剩余显存建立KV Cache
        cache_max_entry_count=0.4,

        # 单次prefill的最大token数
        max_prefill_token_num=2048,

        # 测试阶段使用eager模式，减少CUDA Graph变量
        eager_mode=True,

        # False表示完整加载视觉编码器
        # 之后也可以直接进行图片推理测试
        disable_vision_encoder=False,
    )

    # 使用确定性生成，方便判断结果是否稳定
    generation_config = GenerationConfig(
        do_sample=False,
        max_new_tokens=256,
    )

    messages = [
        {
            "role": "user",
            "content": (
                "请用三句话介绍一下你自己，"
                "并说明你擅长处理哪些任务。"
            ),
        }
    ]

    print("\n正在使用LMDeploy加载标准BF16模型……")
    print("张量并行: TP=2")
    print("数据类型: BF16")
    print("首次启动需要加载权重并编译Triton算子，请耐心等待。\n")

    with pipeline(
        str(MODEL_PATH),
        backend_config=backend_config,
        trust_remote_code=True,
        log_level="INFO",
    ) as pipe:
        print("\n✅ 模型加载成功")
        print("正在生成回答……\n")

        response = pipe(
            messages,
            gen_config=generation_config,
        )

        print("=" * 70)
        print("模型回答")
        print("=" * 70)

        response_text = getattr(response, "text", None)

        if response_text is not None:
            print(response_text)
        else:
            print(response)


if __name__ == "__main__":
    main()
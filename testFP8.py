from lmdeploy import GenerationConfig, PytorchEngineConfig, pipeline

MODEL_PATH = "/models/Intern-S2-Preview-FP8"


def main() -> None:
    print("正在使用 LMDeploy 加载本地 FP8 模型……")
    print("模型目录:", MODEL_PATH)

    # tp=2：使用两张 GPU 做张量并行
    # session_len=4096：本次只做短文本冒烟测试
    # cache_max_entry_count=0.5：最多使用约一半空闲显存作为 KV Cache
    backend_config = PytorchEngineConfig(
        tp=2,
        session_len=4096,
        cache_max_entry_count=0.5,
    )

    generation_config = GenerationConfig(
        do_sample=True,
        temperature=0.8,
        top_p=0.95,
        top_k=50,
        max_new_tokens=256,
    )

    messages = [
        {
            "role": "user",
            "content": "你好，请用三句话介绍一下你自己，并说明你擅长处理哪些任务。",
        }
    ]

    # with 结束后自动释放 LMDeploy Pipeline 和 GPU 资源
    with pipeline(
        MODEL_PATH,
        backend_config=backend_config,
        trust_remote_code=True,
        log_level="INFO",
    ) as pipe:
        print("\n✅ 模型加载完成")
        print("正在进行本地推理……\n")

        response = pipe(
            messages,
            gen_config=generation_config,
        )

        print("=" * 70)
        print("LMDeploy 原始响应")
        print("=" * 70)
        print(response)

        # 不同 LMDeploy 版本的响应对象展示方式可能略有不同
        response_text = getattr(response, "text", None)

        if response_text is not None:
            print("\n" + "=" * 70)
            print("模型回答")
            print("=" * 70)
            print(response_text)


if __name__ == "__main__":
    main()
import openai
import httpx
import os
from typing import List, Dict
from google import genai

class LLMClient:
    """一个统一的、简化的LLM客户端，支持OpenAI兼容接口和Google Gemini，并统一处理代理。"""
    def __init__(self, config: dict):
        self.full_config = config
        self.provider = config.get("provider", "openai")
        provider_cfg = config.get(self.provider, {})
        
        proxy_url = provider_cfg.get("proxy_url")
        self.model = provider_cfg.get("model")
        api_key = provider_cfg.get("api_key")

        if self.provider == "google":
            if proxy_url:
                os.environ["HTTP_PROXY"] = proxy_url
                os.environ["HTTPS_PROXY"] = proxy_url
            else:
                if "HTTP_PROXY" in os.environ:
                    del os.environ["HTTP_PROXY"]
                if "HTTPS_PROXY" in os.environ:
                    del os.environ["HTTPS_PROXY"]
            self.client = genai.Client(api_key=api_key)
        else:  # openai 兼容
            http_client = httpx.Client(proxy=proxy_url or None)
            self.client = openai.OpenAI(
                api_key=api_key,
                base_url=provider_cfg.get("api_base", ""),
                http_client=http_client,
            )

    def call(self, messages: List[Dict], json_mode: bool = False) -> str:
        """根据提供商调用相应的LLM API"""
        if self.provider == "google":
            generation_config_params = {}
            generation_config_params["temperature"] = 0.1
            generation_config_params["top_p"] = 0.1
            if json_mode:
                generation_config_params["response_mime_type"] = "application/json"
            config = genai.types.GenerateContentConfig(**generation_config_params)
            response = self.client.models.generate_content(
                model=self.model, 
                config=config,
                contents=messages[0]["content"],
            )
            
            raw_text = response.text
            if json_mode:
                # 查找第一个 '{' 和最后一个 '}' 来提取潜在的JSON字符串,这可以处理模型返回被markdown代码块包裹或带有前缀文本的JSON
                start = raw_text.find('{')
                end = raw_text.rfind('}')
                if start != -1 and end != -1 and start < end:
                    return raw_text[start:end+1]
            return raw_text
        else: # openai 兼容
            extra_params = {"response_format": {"type": "json_object"}} if json_mode else {}
            
            # 检查是否存在非标准的 `enable_thinking` 参数，并将其设置为 False
            # 使用 extra_body 来传递非标准参数，以避免库验证错误
            extra_body = {}
            extra_body["enable_thinking"] = False

            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.1,
                top_p=0.1,
                messages=messages,
                extra_body=extra_body,
                **extra_params,
            )
            return response.choices[0].message.content

"""Azure OpenAI provider.

Azure exposes the OpenAI Chat Completions API at a per-deployment URL.
The shape is OpenAI-compatible, so we re-use OpenAIClient — but the
base URL + auth header differ:

  - base_url: https://<resource>.openai.azure.com/openai/deployments/<deployment>
  - the model is the *deployment name*, not the OpenAI model id
  - an ``api-version`` query param is required

Env:
  - AZURE_OPENAI_ENDPOINT  (e.g. https://my-res.openai.azure.com)
  - AZURE_OPENAI_API_KEY
  - AZURE_OPENAI_DEPLOYMENT (the deployment/model name)
  - AZURE_OPENAI_API_VERSION (default 2024-10-21)
"""
from __future__ import annotations

import os
from typing import Optional

from .openai_provider import OpenAIClient


class AzureOpenAIClient(OpenAIClient):
    DEFAULT_MODEL = "azure-deployment"

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        endpoint = (
            base_url
            or os.environ.get("AZURE_OPENAI_ENDPOINT")
            or ""
        ).rstrip("/")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
        version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
        if not endpoint or not deployment:
            raise RuntimeError(
                "Azure OpenAI requires AZURE_OPENAI_ENDPOINT + "
                "AZURE_OPENAI_DEPLOYMENT (+ AZURE_OPENAI_API_KEY)."
            )
        # Azure routes per-deployment; the OpenAI SDK base_url points at
        # the deployment, and the api-version is a query param.
        url = (
            f"{endpoint}/openai/deployments/{deployment}"
            f"?api-version={version}"
        )
        key = api_key or os.environ.get("AZURE_OPENAI_API_KEY") or "azure-no-auth"
        super().__init__(api_key=key, base_url=url)
        # Azure uses the deployment name where OpenAI uses the model id.
        self.DEFAULT_MODEL = deployment

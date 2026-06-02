import os

# OpenAI API Configuration
# Always loaded from the OPENAI_API_KEY environment variable.
#   bash:        export OPENAI_API_KEY=sk-...
#   PowerShell:  $env:OPENAI_API_KEY = "sk-..."
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise EnvironmentError(
        "OPENAI_API_KEY environment variable is not set. "
        "Set it before running anything that imports core.llm."
    )

# Model name - change this to use different models
MODEL_NAME = "gpt-4.1-mini"

# Alternative models:
# MODEL_NAME = "gpt-4"
# MODEL_NAME = "gpt-4-turbo"
# MODEL_NAME = "gpt-3.5-turbo"

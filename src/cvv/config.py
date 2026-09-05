"""Settings, from the environment or a .env file.

Everything that varies by machine lives here — hosts, tokens, and the one setting that
decides whether extraction is reproducible across model reloads.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CVV_", env_file=".env", extra="ignore")

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:1.7b"

    # num_ctx defaults to 4096 in Ollama and truncates SILENTLY. Claims from the bottom
    # of a CV vanish with no error, so it is always set explicitly.
    num_ctx: int = 8192

    # Fixed seed + temperature 0. Necessary for reproducibility, and — measured — not
    # sufficient on its own; see num_gpu.
    seed: int = 7

    # How many model layers to place on the GPU. None lets Ollama decide from whatever
    # VRAM happens to be free, and that is the one measured source of non-determinism
    # in this system.
    #
    # qwen3:1.7b is 2.4 GB at num_ctx 8192 and does not fit a 4 GB card, so Ollama
    # splits it. The split moves with what else is using VRAM — observed at 83%, 86%
    # and 89% GPU across sessions on the same machine. A different split is a different
    # arithmetic path, and at temperature 0 a tiny floating-point difference flips the
    # argmax on a near-tie. Generation is then exactly deterministic WITHIN a load
    # session and can differ ACROSS them: the skills pass returned 18 items in one
    # session and 22 in another, from the same document and seed.
    #
    # Pinning it makes the split independent of free VRAM. Pick a value that fits with
    # headroom on the target machine — qwen3:1.7b has 28 blocks — and record it in the
    # report's provenance, because a stored report should say which configuration
    # produced it.
    #
    # The deterministic layer absorbed that variance in every observed case: the final
    # claim set was byte-identical whether the model proposed 18 items or 22. This
    # removes the variance at source rather than relying on that holding.
    num_gpu: int | None = None

    github_token: str | None = None  # a PAT is enough; App auth is not needed yet

    request_timeout: float = 600.0


settings = Settings()

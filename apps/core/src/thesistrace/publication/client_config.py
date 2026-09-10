from botocore.config import Config

PUBLICATION_REQUEST_TIMEOUT_SECONDS = 5.0


def publication_request_config() -> Config:
    return Config(
        connect_timeout=PUBLICATION_REQUEST_TIMEOUT_SECONDS,
        read_timeout=PUBLICATION_REQUEST_TIMEOUT_SECONDS,
        retries={"total_max_attempts": 1, "mode": "standard"},
    )

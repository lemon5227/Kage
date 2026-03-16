from core.model_broker import ModelBroker


def test_model_broker_defaults_to_local_roles_without_cloud_key():
    broker = ModelBroker(
        {
            "model": {
                "local_runtime": {"host": "127.0.0.1", "port": 8080, "timeout_sec": 30},
                "cloud_api": {"api_key": ""},
                "broker": {
                    "routing_provider": "local",
                    "realtime_provider": "local",
                    "background_provider": "local",
                    "fallback_provider": "cloud",
                },
            }
        }
    )

    assert broker.profile("routing").mode == "local"
    assert broker.profile("realtime").mode == "local"
    assert broker.profile("background").mode == "local"
    assert broker.profile("fallback_cloud").mode == "local"


def test_model_broker_uses_cloud_when_configured():
    broker = ModelBroker(
        {
            "model": {
                "local_runtime": {"host": "127.0.0.1", "port": 8080, "timeout_sec": 30},
                "cloud_api": {
                    "api_key": "sk-test",
                    "model_name": "gpt-4o-mini",
                    "base_url": "https://api.openai.com/v1",
                    "timeout_sec": 60,
                },
                "broker": {
                    "routing_provider": "local",
                    "realtime_provider": "local",
                    "background_provider": "cloud",
                    "fallback_provider": "cloud",
                },
            }
        }
    )

    assert broker.profile("background").mode == "cloud"
    assert broker.profile("fallback_cloud").mode == "cloud"

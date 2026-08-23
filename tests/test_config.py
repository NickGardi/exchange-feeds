from app.config import Settings


def test_pipeline_mode_off_by_default() -> None:
    settings = Settings(testing=False, cassandra_host="", kafka_bootstrap_servers="")
    assert settings.pipeline_mode is False


def test_pipeline_mode_when_cassandra_configured() -> None:
    settings = Settings(testing=False, cassandra_host="cassandra", kafka_bootstrap_servers="kafka:9092")
    assert settings.pipeline_mode is True


def test_run_local_feeds_overrides_pipeline() -> None:
    settings = Settings(
        testing=False,
        cassandra_host="cassandra",
        kafka_bootstrap_servers="kafka:9092",
        run_local_feeds=True,
    )
    assert settings.pipeline_mode is False


def test_testing_disables_pipeline() -> None:
    settings = Settings(testing=True, cassandra_host="cassandra")
    assert settings.pipeline_mode is False

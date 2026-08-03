from thesistrace.entrypoints.runtime import CoreSettings, open_core_runtime


def test_empty_data_projection_uses_postgres_and_rustfs(
    core_settings: CoreSettings,
) -> None:
    with open_core_runtime(core_settings) as runtime:
        assert runtime.data.overview().model_dump(mode="json") == {
            "status": "idle",
            "latest_release": None,
            "latest_update_outcome": None,
        }
        assert runtime.data.list_releases().model_dump(mode="json") == {
            "items": [],
            "next_cursor": None,
        }
        assert runtime.publication.storage_is_available()


def test_reopening_runtime_preserves_empty_data_state(core_settings: CoreSettings) -> None:
    for _ in range(2):
        with open_core_runtime(core_settings) as runtime:
            assert runtime.data.overview().status == "idle"
            assert runtime.data.list_releases().items == []

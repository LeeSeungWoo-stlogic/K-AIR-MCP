import pytest

from app import catalog_client


@pytest.fixture(autouse=True)
def _fresh_catalog_cache():
    # 카탈로그 TTL 캐시가 테스트 사이에 새지 않게 한다.
    catalog_client.clear_catalog_cache()
    yield
    catalog_client.clear_catalog_cache()

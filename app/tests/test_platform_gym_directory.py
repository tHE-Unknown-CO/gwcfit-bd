from app.api.v1.gyms import list_gyms


def test_platform_directory_includes_inactive_gyms_and_has_stable_pagination():
    class Result:
        def all(self):
            return []
    class Session:
        def scalars(self, statement):
            sql = str(statement.compile())
            assert "WHERE" not in sql
            assert "ORDER BY" in sql
            assert statement.compile().params["param_1"] == 50
            return Result()
    assert list_gyms(skip=50, limit=50, db=Session(), _=None) == []

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


def test_public_directory_returns_each_gyms_hero_photos():
    from datetime import UTC, datetime
    from types import SimpleNamespace as NS
    from uuid import uuid4
    from app.api.v1.gyms import list_public_gym_directory
    rows=[]
    for index in range(2):
        rows.append(NS(_mapping={'id':uuid4(),'name':f'Gym {index}','code':f'G{index}','status':'active','email':None,'phone':None,'address':None,'settings':{'hero_photos':[{'url':f'https://example.com/gym-{index}.jpg','caption':f'Gym {index}'}]},'plan_name':None,'subscription_status':None,'created_at':datetime.now(UTC)}))
    class Session:
        def execute(self,statement): return NS(all=lambda:rows)
    result=list_public_gym_directory(latitude=None,longitude=None,db=Session())
    assert result[0].hero_photos[0].url=='https://example.com/gym-0.jpg'
    assert result[1].hero_photos[0].url=='https://example.com/gym-1.jpg'

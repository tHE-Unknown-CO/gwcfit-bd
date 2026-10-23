from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from app.services import gym_website as service
from app.schemas.gym_website import GymWebsiteEdit, WebsitePerson, WebsitePhoto


def actor(gym_id, role='gym_owner'):
    return NS(id=uuid4(), gym_id=gym_id, role=role, permission_overrides=[])


@pytest.mark.parametrize('role', ['gym_owner', 'trainer', 'member'])
def test_cross_gym_edits_rejected(role):
    with pytest.raises(HTTPException) as error:
        service.authorize_website_editor(actor(uuid4(),role), uuid4())
    assert error.value.status_code == 403


def test_editor_requires_configuration_permission():
    gym_id = uuid4()
    with pytest.raises(HTTPException):
        service.authorize_website_editor(actor(gym_id,'trainer'), gym_id)
    service.authorize_website_editor(actor(gym_id), gym_id)
    service.authorize_website_editor(actor(None,'super_admin'), gym_id)


def test_public_website_queries_only_active_records_for_requested_gym():
    gym_id = uuid4()
    trainer_id, owner_id, plan_id = uuid4(),uuid4(),uuid4()
    gym = NS(id=gym_id,name='My Gym',address='Pune',phone='123',email='gym@example.com',settings={})
    trainer = NS(id=trainer_id,full_name='Coach',extra_data={'photo':'https://example.com/coach.jpg'},bio='Strength coach',specialties=['Strength'],user=None)
    owner = NS(id=owner_id,full_name='Owner',profile={'profile_photo':'https://example.com/owner.jpg','private_field':'secret'})
    plan = NS(id=plan_id,name='Quarterly',description='Access',duration_days=90,price_cents=300000,currency='INR',features=['Training'])
    class Session:
        def scalar(self,statement):
            assert gym_id in statement.compile().params.values()
            assert 'gyms.is_active IS true' in str(statement)
            return gym
        def scalars(self,statement):
            sql = str(statement)
            assert gym_id in statement.compile().params.values()
            table = 'membership_plans' if 'membership_plans' in sql else 'trainers' if 'FROM trainers' in sql else 'users'
            assert f'{table}.gym_id =' in sql
            assert f'{table}.is_active IS true' in sql
            if table == 'users': assert 'gym_owner' in statement.compile().params.values()
            return NS(all=lambda: {'trainers':[trainer],'users':[owner],'membership_plans':[plan]}[table])
    result = service.public_website(Session(),gym_id)
    assert result.membership_plans[0].id == plan_id
    assert result.trainers[0].photo_url.endswith('coach.jpg')
    assert result.owners[0].photo_url.endswith('owner.jpg')
    assert 'private_field' not in result.model_dump_json()
    assert 'email' not in result.owners[0].model_dump()


def test_save_preserves_unrelated_settings_and_rejects_foreign_people(monkeypatch):
    gym_id, trainer_id = uuid4(),uuid4()
    gym = NS(settings={'platform_access_override':'paid','business_phone':'123'},updated_by=None)
    monkeypatch.setattr(service,'website_gym',lambda db,id:gym)
    monkeypatch.setattr(service,'website_team',lambda *args,**kwargs:([WebsitePerson(id=trainer_id,full_name='Coach')],[]))
    monkeypatch.setattr(service,'public_website',lambda db,id:gym.settings)
    db = NS(commit=lambda:None,refresh=lambda gym:None)
    payload = GymWebsiteEdit(categories=['Yoga'],hidden_trainer_ids=[uuid4()])
    with pytest.raises(HTTPException) as error:
        service.save_website(db,gym_id,payload,actor(gym_id))
    assert error.value.status_code == 422
    assert gym.settings == {'platform_access_override':'paid','business_phone':'123'}
    payload.hidden_trainer_ids=[trainer_id]
    result = service.save_website(db,gym_id,payload,actor(gym_id))
    assert result['platform_access_override'] == 'paid'
    assert result['business_phone'] == '123'
    assert result['categories'] == ['Yoga']
    assert result['hidden_trainer_ids'] == [str(trainer_id)]


def test_photo_urls_and_labels_are_validated():
    for url in ('javascript:alert(1)','data:text/html;base64,xxx','//other.example/photo.jpg',''):
        with pytest.raises(ValidationError): WebsitePhoto(url=url)
    assert WebsitePhoto(url='https://example.com/gym.jpg').url
    assert WebsitePhoto(url='data:image/webp;base64,YWJj').url
    assert GymWebsiteEdit(categories=[' Yoga ','Yoga']).categories == ['Yoga']


def test_hidden_profiles_stay_out_of_public_team():
    gym_id, trainer_id = uuid4(),uuid4()
    trainer = NS(id=trainer_id,full_name='Coach',extra_data={},bio=None,specialties=[],user=None)
    class Session:
        def scalars(self,statement):
            return NS(all=lambda:[trainer] if 'FROM trainers' in str(statement) else [])
    settings={'hidden_trainer_ids':[str(trainer_id)]}
    assert service.website_team(Session(),gym_id,settings)[0] == []
    assert service.website_team(Session(),gym_id,settings,include_hidden=True)[0][0].id == trainer_id


def test_editor_http_rejects_foreign_gym_before_loading_database():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database.session import get_db
    from app.dependencies.auth import get_current_user
    gym_id = uuid4()
    class NoDatabase:
        def scalar(self,*args): raise AssertionError('Must authorize before database read')
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: NoDatabase()
    app.dependency_overrides[get_current_user] = lambda: actor(uuid4())
    try:
        client = TestClient(app)
        assert client.get(f'/api/v1/gyms/{gym_id}/website').status_code == 403
        assert client.patch(f'/api/v1/gyms/{gym_id}/website',json={'categories':['Yoga']}).status_code == 403
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_editor_discards_selections_for_deactivated_team_records():
    inactive_id, active_id = uuid4(),uuid4()
    profile = service.edit_profile({'hidden_trainer_ids':[str(inactive_id),str(active_id)],'trainer_overrides':[{'id':str(inactive_id),'bio':'Former coach'}]},[WebsitePerson(id=active_id,full_name='Active Coach')],[])
    assert profile.hidden_trainer_ids == [active_id]
    assert profile.trainer_overrides == []


@pytest.mark.parametrize('role', ['sub_admin', 'trainer', 'receptionist', 'member'])
def test_other_roles_cannot_edit_even_with_configuration_permission(role):
    gym_id = uuid4()
    user = actor(gym_id,role)
    user.permission_overrides = [NS(permission='configure_gym',allowed=True)]
    with pytest.raises(HTTPException) as error:
        service.authorize_website_editor(user,gym_id)
    assert error.value.status_code == 403


def test_super_admin_can_edit_any_gym():
    user = actor(None,'super_admin')
    service.authorize_website_editor(user,uuid4())
    service.authorize_website_editor(user,uuid4())


def test_hero_backgrounds_are_editable_and_limited_to_ten():
    photos=[{'url':'https://example.com/hero.jpg','caption':'Gym floor'}]
    profile=GymWebsiteEdit(hero_photos=photos)
    assert profile.model_dump(mode='json')['hero_photos'] == photos
    assert service.edit_profile(profile.model_dump(mode='json')).hero_photos[0].caption == 'Gym floor'
    with pytest.raises(ValidationError): GymWebsiteEdit(hero_photos=photos * 11)


@pytest.mark.parametrize('fields', [
    {'latitude':91,'longitude':0}, {'latitude':0,'longitude':181},
    {'latitude':18.5}, {'business_email':'not-an-email'},
    {'opening_hours':{'Monday':{'open':'25:00','close':'22:00'}}},
    {'opening_hours':{'Monday':{'closed':False}}},
])
def test_contact_validation(fields):
    with pytest.raises(ValidationError): GymWebsiteEdit(**fields)


def test_contact_save_updates_gym_and_preserves_other_settings(monkeypatch):
    gym_id=uuid4()
    gym=NS(name='Old gym',address='Old address',settings={'city':'Old city','platform_access_override':'paid','categories':['Yoga']},updated_by=None)
    monkeypatch.setattr(service,'website_gym',lambda *args:gym)
    monkeypatch.setattr(service,'website_team',lambda *args,**kwargs:([],[]))
    monkeypatch.setattr(service,'public_website',lambda *args:gym)
    db=NS(commit=lambda:None,refresh=lambda gym:None)
    payload=GymWebsiteEdit(name='Updated gym',address='New street',city='Pune',business_phone='12345',business_email='gym@example.com',latitude=0,longitude=0,opening_hours={'Monday':{'open':'06:00','close':'22:00'},'Sunday':{'closed':True}})
    service.save_website(db,gym_id,payload,actor(gym_id))
    assert gym.name=='Updated gym'
    assert gym.address=='New street'
    assert 'name' not in gym.settings and 'address' not in gym.settings
    assert gym.settings['platform_access_override']=='paid'
    assert gym.settings['categories']==['Yoga']
    assert gym.settings['opening_hours']['Sunday']['closed'] is True
    assert gym.settings['latitude']==0 and gym.settings['longitude']==0
    gym.phone='legacy phone';gym.email='old@example.com'
    profile=service.edit_profile(gym.settings,[],[],gym)
    assert profile.address=='New street'
    assert profile.city=='Pune'
    assert profile.name=='Updated gym'
    assert profile.business_email=='gym@example.com'


def test_social_links_validate_urls_and_survive_profile_roundtrip():
    profile=GymWebsiteEdit(social_links=[{'platform':'instagram','url':'https://instagram.com/mygym'},{'platform':'facebook','url':'https://facebook.com/mygym'},{'platform':'other','url':'https://example.com/community','label':'Community'}])
    saved=profile.model_dump(mode='json')
    restored=service.edit_profile(saved)
    assert restored.social_links[0].platform=='instagram'
    assert str(restored.social_links[1].url)=='https://facebook.com/mygym'
    assert restored.social_links[2].label=='Community'
    for url in ['javascript:alert(1)','file:///test','//example.com','']:
        with pytest.raises(ValidationError): GymWebsiteEdit(social_links=[{'platform':'instagram','url':url}])
    with pytest.raises(ValidationError): GymWebsiteEdit(social_links=[{'platform':'unsupported','url':'https://example.com'}])
    with pytest.raises(ValidationError): GymWebsiteEdit(social_links=[{'platform':'website','url':'https://example.com'}]*21)

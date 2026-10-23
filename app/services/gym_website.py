from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from app.models.gym import Gym
from app.models.plans import MembershipPlan
from app.models.trainer import Trainer
from app.models.user import User
from app.models.enums import PermissionCode
from app.permissions.rbac import has_permission
from app.schemas.gym_website import GymWebsiteEdit, GymWebsiteRead, WebsitePerson, WebsiteMembershipPlan


def website_gym(db, gym_id):
    gym = db.scalar(select(Gym).where(Gym.id == gym_id, Gym.is_active.is_(True)))
    if gym is None:
        raise HTTPException(404, 'Gym was not found.')
    return gym


def authorize_website_editor(user, gym_id):
    # The developer account uses the platform's super_admin role.
    if user.role == 'super_admin':
        return
    if user.role != 'gym_owner':
        raise HTTPException(403, 'Only the gym owner or super admin/developer can edit this website.')
    if user.gym_id != gym_id:
        raise HTTPException(403, 'You can only edit your own gym website.')
    if not has_permission(user, PermissionCode.CONFIGURE_GYM):
        raise HTTPException(403, 'Gym configuration access is required.')


def website_team(db, gym_id, settings, include_hidden=False):
    trainers = db.scalars(select(Trainer).options(joinedload(Trainer.user)).where(Trainer.gym_id == gym_id, Trainer.is_active.is_(True)).order_by(Trainer.full_name)).all()
    owners = db.scalars(select(User).where(User.gym_id == gym_id, User.role == 'gym_owner', User.is_active.is_(True)).order_by(User.full_name)).all()
    def people(records, kind):
        overrides = {str(item['id']): item for item in settings.get(f'{kind}_overrides', [])}
        hidden = {str(item) for item in settings.get(f'hidden_{kind}_ids', [])}
        result = []
        for record in records:
            if not include_hidden and str(record.id) in hidden:
                continue
            extra = (record.extra_data or {}) if kind == 'trainer' else (record.profile or {})
            override = overrides.get(str(record.id), {})
            user = record.user if kind == 'trainer' else None
            user_profile = (user.profile or {}) if user and user.gym_id == gym_id and user.is_active else {}
            photo = extra.get('photo') or extra.get('profile_photo') or extra.get('photo_url') or user_profile.get('profile_photo')
            result.append(WebsitePerson(id=record.id, full_name=record.full_name, photo_url=override.get('photo_url') or photo, bio=override.get('bio') if override.get('bio') is not None else getattr(record, 'bio', None) or extra.get('bio'), specialties=getattr(record, 'specialties', []) or []))
        return result
    return people(trainers, 'trainer'), people(owners, 'owner')


def public_website(db, gym_id):
    gym = website_gym(db, gym_id)
    settings = gym.settings or {}
    trainers, owners = website_team(db, gym_id, settings)
    plans = db.scalars(select(MembershipPlan).where(MembershipPlan.gym_id == gym_id, MembershipPlan.is_active.is_(True)).order_by(MembershipPlan.price_cents, MembershipPlan.name)).all()
    address = ', '.join(str(part).strip() for part in [gym.address, settings.get('city'), settings.get('state'), settings.get('pincode')] if part and str(part).strip()) or None
    fields = {key: settings[key] for key in ('description','latitude','longitude','categories','facilities','gallery_photos','hero_photos','social_links','opening_hours','gender_policy','verified','trial_available') if key in settings}
    return GymWebsiteRead(id=gym.id, name=gym.name, address=address, business_phone=settings.get('business_phone', gym.phone), business_email=settings.get('business_email', gym.email), trainers=trainers, owners=owners, membership_plans=[WebsiteMembershipPlan(id=p.id, name=p.name, description=p.description, duration_days=p.duration_days, price_cents=p.price_cents, currency=p.currency, features=p.features or []) for p in plans], **fields)


def edit_profile(settings, trainers=None, owners=None, gym=None):
    profile = GymWebsiteEdit(**{key: value for key, value in (settings or {}).items() if key in GymWebsiteEdit.model_fields})
    if gym is not None:
        profile.name = gym.name
        profile.address = gym.address
        profile.business_phone = (settings or {}).get('business_phone', gym.phone)
        profile.business_email = (settings or {}).get('business_email', gym.email)
    # Deactivated team records should not leave stale selections in the editor.
    for kind, records in [('trainer', trainers), ('owner', owners)]:
        if records is None:
            continue
        allowed = {person.id for person in records}
        setattr(profile, f'hidden_{kind}_ids', [id for id in getattr(profile, f'hidden_{kind}_ids') if id in allowed])
        setattr(profile, f'{kind}_overrides', [person for person in getattr(profile, f'{kind}_overrides') if person.id in allowed])
    return profile


def save_website(db, gym_id, payload, user):
    authorize_website_editor(user, gym_id)
    gym = website_gym(db, gym_id)
    trainers, owners = website_team(db, gym_id, gym.settings or {}, include_hidden=True)
    for kind, people in [('trainer', trainers), ('owner', owners)]:
        allowed = {person.id for person in people}
        requested = set(getattr(payload, f'hidden_{kind}_ids')) | {person.id for person in getattr(payload, f'{kind}_overrides')}
        if not requested.issubset(allowed):
            raise HTTPException(422, 'Select people belonging to this gym only.')
    changes = payload.model_dump(mode='json', exclude_unset=True)
    for key in ('name', 'address'):
        if key in changes:
            value = changes.pop(key)
            if key != 'name' or value is not None:
                setattr(gym, key, value)
    gym.settings = {**(gym.settings or {}), **changes}
    gym.updated_by = user.id
    db.commit()
    db.refresh(gym)
    return public_website(db, gym_id)

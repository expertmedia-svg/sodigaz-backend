from datetime import datetime, timedelta
from uuid import uuid4

from app.auth import hash_password
from app.models import (
    BottleTypeEnum,
    Delivery,
    DeliveryStatusEnum,
    Depot,
    GPSLog,
    Preorder,
    PreorderStatusEnum,
    RoleEnum,
    Truck,
    User,
)


def _create_user(db, *, email, username, role, full_name):
    user = User(
        email=email,
        username=username,
        full_name=full_name,
        hashed_password=hash_password('secret123'),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client, username):
    response = client.post(
        '/api/auth/login',
        json={'username': username, 'password': 'secret123'},
    )
    assert response.status_code == 200
    return response.json()['access_token']


def _seed_assignment_context(db):
    suffix = uuid4().hex[:8]
    depot_manager = _create_user(
        db,
        email=f'depot-assign-{suffix}@example.com',
        username=f'depot_assign_{suffix}',
        role=RoleEnum.DEPOT,
        full_name='Depot Manager',
    )
    driver = _create_user(
        db,
        email=f'driver-assign-{suffix}@example.com',
        username=f'driver_assign_{suffix}',
        role=RoleEnum.RAVITAILLEUR,
        full_name='Driver Assign',
    )
    customer = _create_user(
        db,
        email=f'customer-alert-{suffix}@example.com',
        username=f'customer_alert_{suffix}',
        role=RoleEnum.USER,
        full_name='Customer Alert',
    )

    depot = Depot(
        name=f'Depot Affectation {suffix}',
        manager_id=depot_manager.id,
        latitude=12.3714,
        longitude=-1.5197,
        stock_6kg_plein=30,
        stock_12kg_plein=18,
        stock_6kg_vide=4,
        stock_12kg_vide=2,
        capacity_6kg=80,
        capacity_12kg=50,
        address='Secteur 10',
        city='Ouagadougou',
        phone='70000001',
    )
    db.add(depot)
    db.commit()
    db.refresh(depot)

    truck = Truck(
        license_plate=f'DEP-ASSIGN-{suffix}',
        driver_id=driver.id,
        capacity_6kg=90,
        capacity_12kg=60,
        current_load_6kg_plein=15,
        current_load_12kg_plein=10,
    )
    db.add(truck)
    db.commit()
    db.refresh(truck)

    delivery = Delivery(
        truck_id=truck.id,
        depot_id=depot.id,
        destination_name='Boutique Centre',
        destination_address='Avenue centrale',
        destination_latitude=12.3720,
        destination_longitude=-1.5201,
        contact_name='Boutique Centre',
        contact_phone='71000000',
        quantity_6kg=0,
        quantity_12kg=8,
        quantity=8,
        scheduled_date=datetime.utcnow() + timedelta(hours=1),
        status=DeliveryStatusEnum.PENDING,
        driver_id=None,
    )
    db.add(delivery)

    preorder = Preorder(
        user_id=customer.id,
        depot_id=depot.id,
        bottle_type=BottleTypeEnum.B12KG,
        quantity=1,
        status=PreorderStatusEnum.CONFIRMEE,
        created_at=datetime.utcnow(),
    )
    db.add(preorder)
    db.commit()
    db.refresh(delivery)
    db.refresh(preorder)

    return {
        'depot_manager': depot_manager,
        'driver': driver,
        'customer': customer,
        'depot': depot,
        'truck': truck,
        'delivery': delivery,
        'preorder': preorder,
    }


def test_depot_can_list_and_assign_available_drivers(client, db):
    context = _seed_assignment_context(db)
    token = _login(client, context['depot_manager'].username)

    response = client.get(
        '/api/depot/available-drivers',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]['id'] == context['driver'].id
    assert payload[0]['truck_plate'] == context['truck'].license_plate

    response = client.post(
        f"/api/depot/assign-delivery/{context['delivery'].id}",
        headers={'Authorization': f'Bearer {token}'},
        json={'driver_id': context['driver'].id},
    )

    assert response.status_code == 200
    assignment = response.json()['delivery']
    assert assignment['driver_id'] == context['driver'].id
    assert assignment['truck_plate'] == context['truck'].license_plate

    db.refresh(context['delivery'])
    assert context['delivery'].driver_id == context['driver'].id
    assert context['delivery'].truck_id == context['truck'].id
    assert 'Affectée par Depot Manager' in (context['delivery'].notes or '')


def test_customer_gets_delivery_near_alerts_for_active_preorders(client, db):
    context = _seed_assignment_context(db)
    context['delivery'].driver_id = context['driver'].id
    db.commit()

    db.add(
        GPSLog(
            truck_id=context['truck'].id,
            delivery_id=context['delivery'].id,
            latitude=12.3716,
            longitude=-1.5199,
            accuracy=8.0,
            timestamp=datetime.utcnow() - timedelta(minutes=5),
        )
    )
    db.commit()

    token = _login(client, context['customer'].username)
    response = client.get(
        '/api/user/delivery-near-alerts',
        headers={'Authorization': f'Bearer {token}'},
        params={'threshold_km': 2.0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['count'] == 1
    alert = payload['alerts'][0]
    assert alert['delivery_id'] == context['delivery'].id
    assert alert['depot_id'] == context['depot'].id
    assert alert['driver_name'] == 'Driver Assign'
    assert alert['truck_plate'] == context['truck'].license_plate
    assert context['preorder'].id in alert['preorder_ids']
    assert alert['distance_km'] <= 2.0
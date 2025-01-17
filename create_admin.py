from app import db, User, app

def create_admin():
    # Check if admin already exists
    with app.app_context():
        existing_admin = User.query.filter_by(username='admin').first()
        if existing_admin:
            print("Admin user already exists!")
            return
            
        admin = User(
            user_id='0000',
            username='admin',
            password='admin123',
            email='admin@library.com',
            department='Library',
            phone='1234567890',
            gender='other',
            is_admin=True  # Make sure this is True
        )
        db.session.add(admin)
        db.session.commit()
        print("Admin user created successfully!")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin()
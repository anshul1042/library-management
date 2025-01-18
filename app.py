# app.py
from flask import Flask, render_template, request, redirect, session, flash, Response, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import qrcode
import os
from flask import url_for
from functools import wraps

# Update database configuration
db_path = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
if db_path.startswith("postgres://"):
    db_path = db_path.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = db_path
app.config['SECRET_KEY'] = 'your_secret_key'
db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(10), unique=True, nullable=False)  # Add this line
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(80))
    phone = db.Column(db.String(20))
    gender = db.Column(db.String(10))
    is_admin = db.Column(db.Boolean, default=False)
    borrowed_books = db.relationship('BorrowRecord', backref='user', lazy=True)

class Shelf(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(200))
    racks = db.relationship('Rack', backref='shelf', lazy=True)
    qr_code = db.Column(db.String(200))

class Rack(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shelf_id = db.Column(db.Integer, db.ForeignKey('shelf.id'))
    books = db.relationship('Book', backref='rack', lazy=True)

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(200))
    quantity = db.Column(db.Integer, default=1)
    rack_id = db.Column(db.Integer, db.ForeignKey('rack.id'))
    borrow_records = db.relationship('BorrowRecord', backref='book', lazy=True)

class BorrowRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'))
    # Add backup fields for book details
    book_name = db.Column(db.String(200))
    book_author = db.Column(db.String(200))
    borrow_date = db.Column(db.DateTime, default=datetime.utcnow)
    return_date = db.Column(db.DateTime)
    returned = db.Column(db.Boolean, default=False)

# Routes

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # Add no-cache headers to redirect
            response = redirect('/login')
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
            
        # Add cache control headers to response
        response = make_response(f(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
        
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    response = Response()
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'

    if request.method == 'POST':
        user_id = request.form.get('user_id')
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(user_id=user_id).first()

        if user and user.username == username and user.password == password:
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            session['username'] = user.username  # Add this line to store username
            
            if user.is_admin:
                response = redirect('/admin/dashboard')
            else:
                return_to = request.args.get('next') or '/'
                response = redirect(return_to)
            
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
            
        flash('Invalid credentials. Please check your User ID, Username and Password.', 'error')
    return render_template('login.html')

@app.route('/')
@login_required
def home():
    user = User.query.get(session['user_id'])
    if user.is_admin:
        return redirect('/admin/dashboard')
    
    now = datetime.utcnow()
    
    # Get borrowed books stats
    borrowed_books = BorrowRecord.query.filter_by(
        user_id=session['user_id'], 
        returned=False
    ).all()
    
    stats = {
        'total_borrowed': len(borrowed_books),
        'overdue': len([b for b in borrowed_books if b.return_date < now]),
        'can_reissue': len([b for b in borrowed_books if (b.return_date - now).days <= 5 and b.return_date > now])
    }
    
    return render_template('user_dashboard.html', 
                         shelves=Shelf.query.all(), 
                         borrowed_books=borrowed_books,
                         stats=stats,
                         now=now)

# Add new routes for reissue and return
@app.route('/reissue/<int:record_id>', methods=['POST'])
@login_required
def reissue_book(record_id):
    if 'user_id' not in session:
        return redirect('/login')
        
    record = BorrowRecord.query.get_or_404(record_id)
    if record.user_id != session['user_id']:
        flash('Unauthorized action', 'error')
        return redirect('/')
    
    # Add 15 more days from current due date
    record.return_date = record.return_date + timedelta(days=15)
    db.session.commit()
    flash('Book reissued successfully!', 'success')
    return redirect('/')

@app.route('/return/<int:record_id>', methods=['POST'])
@login_required
def user_return_book(record_id):
    if 'user_id' not in session:
        return redirect('/login')
        
    record = BorrowRecord.query.get_or_404(record_id)
    if record.user_id != session['user_id']:
        flash('Unauthorized action', 'error')
        return redirect('/')
    
    # Update book status if book still exists
    record.returned = True
    if record.book:  # Only update quantity if book exists
        record.book.quantity += 1
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'message': 'Book returned successfully!'
        })
    
    flash('Book returned successfully!', 'success')
    return redirect('/')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Generate user ID first
        user_id = generate_next_user_id()
        user = User(
            user_id=user_id,
            username=request.form['username'],
            password=request.form['password'],
            email=request.form['email'],
            department=request.form['department'],
            phone=request.form['phone'],
            gender=request.form['gender']
        )
        db.session.add(user)
        db.session.commit()
        # Add success message with user ID
        flash(f'Registration successful! Your User ID is: {user_id}. Please save this ID for login.', 'success')
        return redirect('/login')
    return render_template('register.html')

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not is_admin():
        return redirect('/')
    
    now = datetime.utcnow()
    
    # Get all borrowed books including deleted ones
    borrowed_books = BorrowRecord.query.filter_by(returned=False)\
        .options(
            db.joinedload(BorrowRecord.user),
            db.joinedload(BorrowRecord.book)
        ).all()
    
    # Get all shelves with eager loading
    shelves = Shelf.query.options(
        db.joinedload(Shelf.racks).joinedload(Rack.books)
    ).all()
    
    # Get all books excluding deleted ones
    all_books = Book.query.filter(Book.rack_id.isnot(None)).all()
    
    # Get all non-admin users
    all_users = User.query.filter_by(is_admin=False).all()
    
    # Get overdue books
    overdue_books = [record for record in borrowed_books if record.return_date < now]
    for record in overdue_books:
        record.days_overdue = (now - record.return_date).days
    
    stats = {
        'total_books': len(all_books),
        'total_users': len(all_users),
        'total_borrowed': len(borrowed_books),
        'total_overdue': len(overdue_books)
    }
    
    return render_template('admin_dashboard.html',
                         stats=stats,
                         all_books=all_books,
                         all_users=all_users,
                         borrowed_books=borrowed_books,
                         overdue_books=overdue_books,
                         shelves=shelves,
                         now=now)

@app.route('/admin/shelf', methods=['GET', 'POST'])
@login_required
def manage_shelf():
    if not is_admin():
        return redirect('/')
    if request.method == 'POST':
        # Create new shelf with location
        shelf = Shelf(location=request.form['location'])
        db.session.add(shelf)
        db.session.commit()
        
        # Create specified number of racks
        num_racks = int(request.form['num_racks'])
        for i in range(num_racks):
            rack = Rack(shelf_id=shelf.id)
            db.session.add(rack)
        db.session.commit()
        
        # Generate QR code
        generate_qr(shelf.id)
        flash('Shelf created successfully!', 'success')
        return redirect('/admin/dashboard')
    return render_template('manage_shelf.html')

@app.route('/admin/book/<int:rack_id>', methods=['GET', 'POST'])
@login_required
def manage_book(rack_id):
    if not is_admin():
        return redirect('/')
    
    # First get the rack and verify it exists
    rack = Rack.query.get_or_404(rack_id)
    
    if request.method == 'POST':
        try:
            book = Book(
                name=request.form['name'],
                author=request.form['author'],
                quantity=int(request.form['quantity']),  # Convert to int
                rack_id=rack_id
            )
            db.session.add(book)
            db.session.commit()
            flash('Book added successfully!', 'success')
            return redirect(url_for('view_shelf', shelf_id=rack.shelf_id))
        except Exception as e:
            db.session.rollback()
            flash('Error adding book: ' + str(e), 'error')
            return redirect(url_for('manage_book', rack_id=rack_id))
    
    return render_template('manage_book.html', rack_id=rack_id)

@app.route('/admin/shelf/<int:shelf_id>/delete', methods=['POST'])
@login_required
def delete_shelf(shelf_id):
    if not is_admin():
        return redirect('/')
        
    shelf = Shelf.query.get_or_404(shelf_id)
    
    # Handle books and racks
    for rack in shelf.racks:
        for book in rack.books:
            # Check for active borrows
            active_borrows = BorrowRecord.query.filter_by(
                book_id=book.id, 
                returned=False
            ).all()
            
            # Update borrow records with backup data
            for record in active_borrows:
                record.book_name = book.name
                record.book_author = book.author
                record.book_id = None  # Detach from book
            
            db.session.delete(book)
        db.session.delete(rack)
    
    db.session.delete(shelf)
    db.session.commit()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/shelf/<int:shelf_id>')
@login_required
def view_shelf(shelf_id):
    shelf = Shelf.query.get(shelf_id)
    return render_template('shelf.html', shelf=shelf)


# Add edit route for shelf
@app.route('/admin/shelf/<int:shelf_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_shelf(shelf_id):
    if not is_admin():
        return redirect('/')
        
    shelf = Shelf.query.get_or_404(shelf_id)
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        try:
            if action == 'add_racks':
                # Add new racks
                num_racks = int(request.form.get('num_racks', 1))
                for _ in range(num_racks):
                    rack = Rack(shelf_id=shelf.id)
                    db.session.add(rack)
                db.session.commit()
                flash(f'{num_racks} new rack(s) added successfully!', 'success')
                return redirect(url_for('edit_shelf', shelf_id=shelf.id))
                
            elif action == 'update_shelf':
                # Update shelf location
                if shelf.location != request.form['location']:
                    # Delete old QR code if location changed
                    if shelf.qr_code and os.path.exists(shelf.qr_code):
                        try:
                            os.remove(shelf.qr_code)
                            shelf.qr_code = None
                        except:
                            pass
                    shelf.location = request.form['location']
                    db.session.commit()
                    # Generate new QR code
                    generate_qr(shelf.id)
                    flash('Shelf updated successfully!', 'success')
                return redirect('/admin/dashboard')
        except Exception as e:
            db.session.rollback()
            flash('Error updating shelf: ' + str(e), 'error')
            return redirect(url_for('edit_shelf', shelf_id=shelf.id))
    
    return render_template('edit_shelf.html', shelf=shelf)


@app.route('/borrow/<int:book_id>')
def borrow_book(book_id):
    if 'user_id' not in session:
        session['book_to_borrow'] = book_id
        return redirect(url_for('login', next=request.url))
    
    user = User.query.get(session['user_id'])
    if user.is_admin:
        return redirect('/')
        
    book = Book.query.get_or_404(book_id)
    if book.quantity > 0:
        record = BorrowRecord(
            user_id=session['user_id'],
            book_id=book_id,
            book_name=book.name,  # Save book details
            book_author=book.author,
            return_date=datetime.utcnow() + timedelta(days=15)
        )
        book.quantity -= 1
        db.session.add(record)
        db.session.commit()
        flash('Book borrowed successfully!', 'success')
    return redirect(request.referrer or '/')


@app.route('/qr/shelf/<int:shelf_id>')
def qr_view_shelf(shelf_id):
    shelf = Shelf.query.get_or_404(shelf_id)
    # Sort racks by ID to maintain order
    shelf.racks.sort(key=lambda x: x.id)  # Changed from id to x.id
    # Store the current shelf ID in session to track which shelf was scanned
    session['current_shelf_id'] = shelf_id
    return render_template('qr_view.html', shelf=shelf)


@app.route('/admin/return-book/<int:record_id>', methods=['POST'])
@login_required
def return_book(record_id):
    if not is_admin():
        return redirect('/')
        
    record = BorrowRecord.query.get_or_404(record_id)
    
    # First check if book exists and hasn't been returned yet
    if record.book and not record.returned:
        record.book.quantity += 1  # Increment quantity first
        record.returned = True     # Then mark as returned
    else:
        record.returned = True     # Just mark as returned for deleted books
    
    db.session.commit()
    
    # Return updated stats with JSON response for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        now = datetime.utcnow()
        borrowed_books = BorrowRecord.query.filter_by(returned=False).all()
        overdue_books = [r for r in borrowed_books if r.return_date < now]
        
        return jsonify({
            'success': True,
            'message': 'Book returned successfully!',
            'stats': {
                'total_borrowed': len(borrowed_books),
                'total_overdue': len(overdue_books)
            }
        })
    
    flash('Book returned successfully!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/book/<int:book_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_book(book_id):
    if not is_admin():
        return redirect('/')
    
    book = Book.query.get_or_404(book_id)
    
    if request.method == 'POST':
        book.name = request.form['name']
        book.author = request.form['author']
        book.quantity = int(request.form['quantity'])
        db.session.commit()
        flash('Book updated successfully!', 'success')
        return redirect(url_for('admin_dashboard') + '#books-detail')
        
    return render_template('edit_book.html', book=book)

@app.route('/admin/book/<int:book_id>/delete', methods=['POST'])
@login_required
def delete_book(book_id):
    if not is_admin():
        return redirect('/')
    
    book = Book.query.get_or_404(book_id)
    
    # Check for active borrows
    active_borrows = BorrowRecord.query.filter_by(
        book_id=book_id, 
        returned=False
    ).all()
    
    # Update all active borrow records with backup data
    for record in active_borrows:
        record.book_name = book.name
        record.book_author = book.author
        record.book_id = None  # Detach from book
    
    db.session.delete(book)
    try:
        db.session.commit()
        flash('Book deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting book: ' + str(e), 'error')
    
    return redirect(url_for('admin_dashboard') + '#books-detail')

@app.route('/admin/rack/<int:rack_id>/delete', methods=['POST'])
@login_required
def delete_rack(rack_id):
    if not is_admin():
        return redirect('/')
    
    rack = Rack.query.get_or_404(rack_id)
    shelf_id = rack.shelf_id
    db.session.delete(rack)
    db.session.commit()
    flash('Rack deleted successfully!', 'success')
    return redirect(url_for('view_shelf', shelf_id=shelf_id))

@app.route('/browse-library')
@login_required
def browse_library():
    if 'user_id' not in session:
        return redirect('/login')
    
    shelves = Shelf.query.all()
    return render_template('browse_library.html', shelves=shelves)

@app.route('/logout')
def logout():
    # Clear session data
    session.clear()
    # Add cache control headers
    response = redirect('/login')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/borrow-history')
@login_required
def borrow_history():
    if 'user_id' not in session:
        return redirect('/login')
        
    # Get current time
    now = datetime.utcnow()
        
    # Get all borrow records for the user, including returned books
    history = BorrowRecord.query.filter_by(user_id=session['user_id'])\
        .order_by(BorrowRecord.borrow_date.desc())\
        .all()
        
    return render_template('borrow_history.html', 
    history=history,
    now=now)  # Add now variable to template context

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    if not is_admin():
        return redirect('/')
        
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            # Update admin profile
            user.email = request.form.get('email')
            user.department = request.form.get('department')
            user.phone = request.form.get('phone')
            
            # Only update password if provided
            new_password = request.form.get('new_password')
            if new_password and request.form.get('current_password') == user.password:
                user.password = new_password
                
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            
    return render_template('admin_settings.html', 
                user=user,
                theme=session.get('theme', 'light'))



@app.route('/settings', methods=['GET', 'POST'])
@login_required
def user_settings():
    if 'user_id' not in session:
        return redirect('/login')
        
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            # Update user profile
            user.email = request.form.get('email')
            user.department = request.form.get('department')
            user.phone = request.form.get('phone')
            
            # Only update password if provided
            new_password = request.form.get('new_password')
            if new_password and request.form.get('current_password') == user.password:
                user.password = new_password
                
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            
            
        elif action == 'appearance_settings':
            # Store theme preference in session
            session['theme'] = request.form.get('theme', 'light')
            flash('Appearance settings updated!', 'success')
            
    return render_template('settings.html', 
                        user=user,
                        theme=session.get('theme', 'light'))

@app.route('/keep-alive', methods=['POST'])
@login_required
def keep_alive():
    return jsonify({'status': 'ok'})

@app.route('/admin/get-stats')
@login_required
def get_stats():
    if not is_admin():
        return jsonify({'error': 'Unauthorized'}), 403
        
    now = datetime.utcnow()
    borrowed_books = BorrowRecord.query.filter_by(returned=False).all()
    overdue_books = [record for record in borrowed_books if record.return_date < now]
    
    # Only count books that have a valid rack (not deleted)
    total_books = Book.query.filter(Book.rack_id.isnot(None)).count()
    
    stats = {
        'total_books': total_books,
        'total_users': User.query.filter_by(is_admin=False).count(),
        'total_borrowed': len(borrowed_books),
        'total_overdue': len(overdue_books)
    }
    
    return jsonify(stats)

def generate_qr(shelf_id):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    # Use your server's IP address or domain name
    url = f'https://library-management-e3j5.onrender.com/qr/shelf/{shelf_id}'
    qr.add_data(url)
    qr.make(fit=True)
    
    # Create QR code image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Ensure directory exists
    if not os.path.exists('static/qr'):
        os.makedirs('static/qr')
    
    # Save QR code
    img_path = f'static/qr/shelf_{shelf_id}.png'
    img.save(img_path)
    
    # Update shelf with QR code path
    shelf = Shelf.query.get(shelf_id)
    shelf.qr_code = img_path
    db.session.commit()

def is_admin():
    if 'user_id' not in session:
        return False
    user = User.query.get(session['user_id'])
    if user is None:
        return False
    return user.is_admin

def generate_next_user_id():
    last_user = User.query.filter(User.user_id != '0000').order_by(User.user_id.desc()).first()
    if last_user and last_user.user_id:
        try:
            # Handle both string and integer conversions
            last_id = int(last_user.user_id)
            next_id = str(last_id + 1).zfill(4)
            # Ensure ID doesn't exceed 9999
            if last_id >= 9999:
                # Handle overflow by starting over from 0001
                next_id = '0001'
        except (ValueError, TypeError):
            # If conversion fails, start from 0001
            next_id = '0001'
    else:
        # If no users exist (except admin), start from 0001
        next_id = '0001'
        
    # Verify the generated ID is unique
    while User.query.filter_by(user_id=next_id).first() is not None:
        try:
            current_id = int(next_id)
            next_id = str(current_id + 1).zfill(4)
            if current_id >= 9999:
                next_id = '0001'
        except (ValueError, TypeError):
            next_id = '0001'
            
    return next_id

if __name__ == '__main__':
    with app.app_context():
        if not os.path.exists('static/qr'):
            os.makedirs('static/qr')
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
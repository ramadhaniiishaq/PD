from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_from_directory
from flask_mysqldb import MySQL
import MySQLdb.cursors
import os
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime
import hashlib
from secrets import token_hex
import bcrypt

app = Flask(__name__)
app.secret_key =token_hex(16)
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'db_PD'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
app.config['ALLOWED_IMAGES'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['BOOKS_PER_PAGE'] = 12
mysql = MySQL(app)


os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'covers'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs'), exist_ok=True)

def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Silakan login terlebih dahulu', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Akses ditolak. Hanya untuk admin.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    cursor = mysql.connection.cursor()
    
    # Get statistics
    cursor.execute("SELECT COUNT(*) as total FROM buku")
    total_books = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role='user'")
    total_users = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM kategori")
    total_categories = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM riwayat_baca")
    total_reads = cursor.fetchone()['total']
    
    cursor.execute("""
        SELECT b.*, k.nama_kategori,
        (SELECT COUNT(*) FROM riwayat_baca WHERE id_buku = b.id_buku) as jumlah_baca
        FROM buku b 
        LEFT JOIN kategori k ON b.id_kategori = k.id_kategori 
        ORDER BY b.id_buku DESC LIMIT 6
    """)
    recent_books = cursor.fetchall()
    
    cursor.execute("""
        SELECT b.*, k.nama_kategori,
        (SELECT COUNT(*) FROM riwayat_baca WHERE id_buku = b.id_buku) as jumlah_baca
        FROM buku b 
        LEFT JOIN kategori k ON b.id_kategori = k.id_kategori 
        ORDER BY jumlah_baca DESC LIMIT 4
    """)
    popular_books = cursor.fetchall()
    
    cursor.execute("""
        SELECT k.*, COUNT(b.id_buku) as jumlah_buku 
        FROM kategori k 
        LEFT JOIN buku b ON k.id_kategori = b.id_kategori 
        GROUP BY k.id_kategori
        ORDER BY jumlah_buku DESC
    """)
    categories = cursor.fetchall()
    
    return render_template('index.html', 
                         total_books=total_books,
                         total_users=total_users,
                         total_categories=total_categories,
                         total_reads=total_reads,
                         recent_books=recent_books,
                         popular_books=popular_books,
                         categories=categories)

@app.route('/books')
def books():
    cursor = mysql.connection.cursor()
    page = request.args.get('page', 1, type=int)
    category_id = request.args.get('category', type=int)
    search = request.args.get('search', '')
    
    per_page = app.config['BOOKS_PER_PAGE']
    offset = (page - 1) * per_page
    
    query = """
        SELECT b.*, k.nama_kategori,
        (SELECT COUNT(*) FROM bookmark WHERE id_buku = b.id_buku) as bookmark_count,
        (SELECT COUNT(*) FROM riwayat_baca WHERE id_buku = b.id_buku) as baca_count
        FROM buku b 
        LEFT JOIN kategori k ON b.id_kategori = k.id_kategori
        WHERE 1=1
    """
    count_query = "SELECT COUNT(*) as total FROM buku b WHERE 1=1"
    params = []
    
    if category_id:
        query += " AND b.id_kategori = %s"
        count_query += " AND id_kategori = %s"
        params.append(category_id)
    
    if search:
        query += " AND (b.judul LIKE %s OR b.penulis LIKE %s OR b.penerbit LIKE %s)"
        count_query += " AND (judul LIKE %s OR penulis LIKE %s OR penerbit LIKE %s)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])
    
    query += " ORDER BY b.id_buku DESC LIMIT %s OFFSET %s"
    
    if category_id or search:
        count_params = params[:3] if search else params[:1]
        cursor.execute(count_query, count_params)
    else:
        cursor.execute(count_query)
    total_books = cursor.fetchone()['total']
    
    full_params = params + [per_page, offset]
    cursor.execute(query, full_params)
    books = cursor.fetchall()
    
    cursor.execute("SELECT * FROM kategori ORDER BY nama_kategori")
    categories = cursor.fetchall()
    
    total_pages = (total_books + per_page - 1) // per_page
    
    return render_template('books.html', 
                         books=books, 
                         categories=categories,
                         current_page=page,
                         total_pages=total_pages,
                         total_books=total_books,
                         selected_category_id=category_id,
                         search_query=search)

@app.route('/book/<int:book_id>')
def book_detail(book_id):
    cursor = mysql.connection.cursor()
    
    cursor.execute("""
        SELECT b.*, k.nama_kategori,
        (SELECT COUNT(*) FROM bookmark WHERE id_buku = b.id_buku) as bookmark_count,
        (SELECT COUNT(*) FROM riwayat_baca WHERE id_buku = b.id_buku) as baca_count
        FROM buku b 
        LEFT JOIN kategori k ON b.id_kategori = k.id_kategori 
        WHERE b.id_buku = %s
    """, (book_id,))
    book = cursor.fetchone()
    
    if not book:
        flash('Buku tidak ditemukan', 'danger')
        return redirect(url_for('books'))
    
    is_bookmarked = False
    if 'user_id' in session:
        cursor.execute("""
            SELECT * FROM bookmark 
            WHERE id_user = %s AND id_buku = %s
        """, (session['user_id'], book_id))
        is_bookmarked = cursor.fetchone() is not None
    
    cursor.execute("""
        SELECT * FROM buku 
        WHERE id_kategori = %s AND id_buku != %s 
        LIMIT 4
    """, (book['id_kategori'], book_id))
    related_books = cursor.fetchall()
    
    return render_template('book_detail.html', 
                         book=book, 
                         is_bookmarked=is_bookmarked,
                         related_books=related_books)

@app.route('/read/<int:book_id>')
@login_required
def read_book(book_id):
    cursor = mysql.connection.cursor()
    
    cursor.execute("SELECT * FROM buku WHERE id_buku = %s", (book_id,))
    book = cursor.fetchone()
    
    if not book:
        flash('Buku tidak ditemukan', 'danger')
        return redirect(url_for('books'))
    
    cursor.execute("""
        INSERT INTO riwayat_baca (id_user, id_buku) 
        VALUES (%s, %s)
    """, (session['user_id'], book_id))
    mysql.connection.commit()
    
    return render_template('read.html', book=book)

@app.route('/view-pdf/<filename>')
@login_required
def view_pdf(filename):
    """Endpoint untuk melihat PDF"""
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs'), filename)

@app.route('/categories')
def categories():
    cursor = mysql.connection.cursor()
    
    cursor.execute("""
        SELECT k.*, COUNT(b.id_buku) as jumlah_buku,
        (SELECT COUNT(*) FROM riwayat_baca rb 
         JOIN buku bb ON rb.id_buku = bb.id_buku 
         WHERE bb.id_kategori = k.id_kategori) as total_baca
        FROM kategori k
        LEFT JOIN buku b ON k.id_kategori = b.id_kategori
        GROUP BY k.id_kategori
        ORDER BY jumlah_buku DESC
    """)
    categories = cursor.fetchall()
    
    return render_template('categories.html', categories=categories)

@app.route('/category/<int:category_id>')
def category_books(category_id):
    cursor = mysql.connection.cursor()
    
    cursor.execute("SELECT * FROM kategori WHERE id_kategori = %s", (category_id,))
    category = cursor.fetchone()
    
    if not category:
        flash('Kategori tidak ditemukan', 'danger')
        return redirect(url_for('categories'))
    
    cursor.execute("""
        SELECT * FROM buku 
        WHERE id_kategori = %s 
        ORDER BY judul
    """, (category_id,))
    books = cursor.fetchall()
    
    return render_template('category_books.html', category=category, books=books)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password'].encode('utf-8')
        
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        
        if user and bcrypt.checkpw(password, user['password'].encode('utf-8')):
            session['user_id'] = user['id_user']
            session['username'] = user['nama']
            session['role'] = user['role']
            session['email'] = user['email']
            
            flash(f'Selamat datang, {user["nama"]}!', 'success')
            
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        else:
            flash('Email atau password salah', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nama = request.form['nama']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('Password tidak cocok', 'danger')
            return redirect(url_for('register'))
        
        cursor = mysql.connection.cursor()
        
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash('Email sudah terdaftar', 'danger')
            return redirect(url_for('register'))
        
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cursor.execute("""
            INSERT IGNORE INTO users (nama, email, password, role) 
            VALUES (%s, %s, %s, 'user')
        """, (nama, email, hashed.decode('utf-8')))
        mysql.connection.commit()
        
        flash('Registrasi berhasil! Silakan login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')
@app.route('/seeder')
def seeder():
    email = 'is@gmail.com'
    password = '123'
    nama = 'saq'
    role = 'admin'
    
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    cursor = mysql.connection.cursor()
    cursor.execute("""
            INSERT IGNORE INTO users (nama, email, password, role) 
            VALUES (%s, %s, %s, %s)
        """, (nama, email,hashed.decode('utf-8'),role))
    mysql.connection.commit()
    cursor.close()
    
    return "Seeder berhasil dijalankan"
@app.route('/logout')
def logout():
    session.clear()
    flash('Anda telah logout', 'info')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    cursor = mysql.connection.cursor()
    
    cursor.execute("SELECT * FROM users WHERE id_user = %s", (session['user_id'],))
    user = cursor.fetchone()
    
    cursor.execute("""
        SELECT rb.*, b.judul, b.penulis, b.cover
        FROM riwayat_baca rb
        JOIN buku b ON rb.id_buku = b.id_buku
        WHERE rb.id_user = %s
        ORDER BY rb.tanggal_baca DESC
        LIMIT 10
    """, (session['user_id'],))
    history = cursor.fetchall()
    
    cursor.execute("""
        SELECT bm.*, b.judul, b.penulis, b.cover
        FROM bookmark bm
        JOIN buku b ON bm.id_buku = b.id_buku
        WHERE bm.id_user = %s
        ORDER BY bm.id_bookmark DESC
    """, (session['user_id'],))
    bookmarks = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) as total FROM riwayat_baca WHERE id_user = %s", (session['user_id'],))
    total_read = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM bookmark WHERE id_user = %s", (session['user_id'],))
    total_bookmark = cursor.fetchone()['total']
    
    return render_template('profile.html', user=user, history=history, bookmarks=bookmarks,total_read=total_read,total_bookmark=total_bookmark,)

@app.route('/bookmark/toggle/<int:book_id>', methods=['POST'])
@login_required
def toggle_bookmark(book_id):
    cursor = mysql.connection.cursor()
    
    cursor.execute("""
        SELECT * FROM bookmark 
        WHERE id_user = %s AND id_buku = %s
    """, (session['user_id'], book_id))
    
    if cursor.fetchone():
        cursor.execute("""DELETE FROM bookmark WHERE id_user = %s AND id_buku = %s""", (session['user_id'], book_id))
        message = 'Buku dihapus dari bookmark'
        bookmarked = False
    else:
        cursor.execute("""
            INSERT INTO bookmark (id_user, id_buku) VALUES (%s, %s)""", (session['user_id'], book_id))
        message = 'Buku ditambahkan ke bookmark'
        bookmarked = True
    
    mysql.connection.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'bookmarked': bookmarked, 'message': message})
    
    flash(message, 'success')
    return redirect(request.referrer or url_for('book_detail', book_id=book_id))

@app.route('/admin')
@admin_required
def admin_dashboard():
    cursor = mysql.connection.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM users")
    total_users = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM users WHERE role='admin'")
    total_admins = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM buku")
    total_books = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM kategori")
    total_categories = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM riwayat_baca")
    total_reads = cursor.fetchone()['total']
    
    cursor.execute("SELECT COUNT(*) as total FROM bookmark")
    total_bookmarks = cursor.fetchone()['total']
    
    cursor.execute("SELECT * FROM users ORDER BY tanggal_daftar DESC LIMIT 5")
    recent_users = cursor.fetchall()
    
    cursor.execute("""
        SELECT b.*, k.nama_kategori 
        FROM buku b 
        LEFT JOIN kategori k ON b.id_kategori = k.id_kategori 
        ORDER BY b.id_buku DESC LIMIT 5
    """)
    recent_books = cursor.fetchall()
    
    cursor.execute("""
        SELECT b.judul, COUNT(rb.id_riwayat) as dibaca
        FROM buku b
        LEFT JOIN riwayat_baca rb ON b.id_buku = rb.id_buku
        GROUP BY b.id_buku
        ORDER BY dibaca DESC
        LIMIT 5
    """)
    popular_books = cursor.fetchall()
    
    return render_template('admin/dashboard.html', total_users=total_users, total_admins=total_admins,total_books=total_books, total_categories=total_categories,
                            total_reads=total_reads,
                            total_bookmarks=total_bookmarks,
                            recent_users=recent_users,
                            recent_books=recent_books,
                            popular_books=popular_books)

@app.route('/admin/books')
@admin_required
def admin_books():
    cursor = mysql.connection.cursor()
    
    cursor.execute("""
        SELECT b.*, k.nama_kategori,
        (SELECT COUNT(*) FROM bookmark WHERE id_buku = b.id_buku) as bookmark_count,
        (SELECT COUNT(*) FROM riwayat_baca WHERE id_buku = b.id_buku) as baca_count
        FROM buku b
        LEFT JOIN kategori k ON b.id_kategori = k.id_kategori
        ORDER BY b.id_buku DESC
    """)
    books = cursor.fetchall()
    
    return render_template('admin/books.html', books=books)

@app.route('/admin/books/add', methods=['GET', 'POST'])
@admin_required
def add_book():
    cursor = mysql.connection.cursor()
    
    if request.method == 'POST':
        judul = request.form['judul']
        penulis = request.form['penulis']
        penerbit = request.form['penerbit']
        tahun_terbit = request.form['tahun_terbit']
        id_kategori = request.form['id_kategori']
        deskripsi = request.form['deskripsi']
        file_buku = request.files['file_buku']
        cover = request.files['cover']
        
        file_buku_filename = None
        cover_filename = None
        
        if file_buku and file_buku.filename != '':
            if allowed_file(file_buku.filename, app.config['ALLOWED_EXTENSIONS']):
                ext = file_buku.filename.rsplit('.', 1)[1].lower()
                file_buku_filename = f"pdf_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
                file_buku.save(os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', file_buku_filename))
            else:
                flash('File buku harus berformat PDF', 'danger')
                return redirect(url_for('add_book'))
        else:
            flash('File buku wajib diupload', 'danger')
            return redirect(url_for('add_book'))
        
        if cover and cover.filename != '':
            if allowed_file(cover.filename, app.config['ALLOWED_IMAGES']):
                ext = cover.filename.rsplit('.', 1)[1].lower()
                cover_filename = f"cover_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
                cover.save(os.path.join(app.config['UPLOAD_FOLDER'], 'covers', cover_filename))
        
        cursor.execute("""
            INSERT INTO buku (judul, penulis, penerbit, tahun_terbit, id_kategori, deskripsi, file_buku, cover)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (judul, penulis, penerbit, tahun_terbit, id_kategori, deskripsi, file_buku_filename, cover_filename))
        mysql.connection.commit()
        
        flash('Buku berhasil ditambahkan', 'success')
        return redirect(url_for('admin_books'))
    
    cursor.execute("SELECT * FROM kategori ORDER BY nama_kategori")
    categories = cursor.fetchall()
    
    return render_template('admin/add_book.html', categories=categories)

@app.route('/admin/books/edit/<int:book_id>', methods=['GET', 'POST'])
@admin_required
def edit_book(book_id):
    cursor = mysql.connection.cursor()
    if request.method == 'POST':
        judul = request.form['judul']
        penulis = request.form['penulis']
        penerbit = request.form['penerbit']
        tahun_terbit = request.form['tahun_terbit']
        id_kategori = request.form['id_kategori']
        deskripsi = request.form['deskripsi']
        
        file_buku = request.files['file_buku']
        if file_buku and file_buku.filename != '':
            if allowed_file(file_buku.filename, app.config['ALLOWED_EXTENSIONS']):
                cursor.execute("SELECT file_buku FROM buku WHERE id_buku = %s", (book_id,))
                old_file = cursor.fetchone()
                if old_file and old_file['file_buku']:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', old_file['file_buku'])
                    if os.path.exists(old_path):
                        os.remove(old_path)
                        
                ext = file_buku.filename.rsplit('.', 1)[1].lower()
                file_buku_filename = f"pdf_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
                file_buku.save(os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', file_buku_filename))
                
                cursor.execute("""
                    UPDATE buku 
                    SET judul=%s, penulis=%s, penerbit=%s, tahun_terbit=%s, id_kategori=%s, deskripsi=%s, file_buku=%s
                    WHERE id_buku=%s
                """, (judul, penulis, penerbit, tahun_terbit, id_kategori, deskripsi, file_buku_filename, book_id))
            else:
                flash('File buku harus berformat PDF', 'danger')
                return redirect(url_for('edit_book', book_id=book_id))
        else:
            cursor.execute("""
                UPDATE buku 
                SET judul=%s, penulis=%s, penerbit=%s, tahun_terbit=%s, id_kategori=%s, deskripsi=%s
                WHERE id_buku=%s
            """, (judul, penulis, penerbit, tahun_terbit, id_kategori, deskripsi, book_id))
        
        cover = request.files['cover']
        if cover and cover.filename != '':
            if allowed_file(cover.filename, app.config['ALLOWED_IMAGES']):
                cursor.execute("SELECT cover FROM buku WHERE id_buku = %s", (book_id,))
                old_cover = cursor.fetchone()
                if old_cover and old_cover['cover']:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], 'covers', old_cover['cover'])
                    if os.path.exists(old_path):
                        os.remove(old_path)
                
                ext = cover.filename.rsplit('.', 1)[1].lower()
                cover_filename = f"cover_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
                cover.save(os.path.join(app.config['UPLOAD_FOLDER'], 'covers', cover_filename))
                
                cursor.execute("UPDATE buku SET cover=%s WHERE id_buku=%s", (cover_filename, book_id))
        
        mysql.connection.commit()
        flash('Buku berhasil diperbarui', 'success')
        return redirect(url_for('admin_books'))
    
    cursor.execute("SELECT * FROM buku WHERE id_buku = %s", (book_id,))
    book = cursor.fetchone()
    
    if not book:
        flash('Buku tidak ditemukan', 'danger')
        return redirect(url_for('admin_books'))
    
    cursor.execute("SELECT * FROM kategori ORDER BY nama_kategori")
    categories = cursor.fetchall()
    
    return render_template('admin/edit_book.html', book=book, categories=categories)

@app.route('/admin/books/delete/<int:book_id>', methods=['POST'])
@admin_required
def delete_book(book_id):
    cursor = mysql.connection.cursor()
    
    cursor.execute("SELECT file_buku, cover FROM buku WHERE id_buku = %s", (book_id,))
    book = cursor.fetchone()
    if book:
        if book['file_buku']:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', book['file_buku'])
            if os.path.exists(file_path):
                os.remove(file_path)
        
        if book['cover']:
            cover_path = os.path.join(app.config['UPLOAD_FOLDER'], 'covers', book['cover'])
            if os.path.exists(cover_path):
                os.remove(cover_path)
    
    cursor.execute("DELETE FROM buku WHERE id_buku = %s", (book_id,))
    mysql.connection.commit()
    
    flash('Buku berhasil dihapus', 'success')
    return redirect(url_for('admin_books'))


@app.route('/admin/categories')
@admin_required
def admin_categories():
    cursor = mysql.connection.cursor()
    
    cursor.execute("""
        SELECT k.*, COUNT(b.id_buku) as jumlah_buku
        FROM kategori k
        LEFT JOIN buku b ON k.id_kategori = b.id_kategori
        GROUP BY k.id_kategori
        ORDER BY k.nama_kategori
    """)
    categories = cursor.fetchall()
    
    return render_template('admin/categories.html', categories=categories)

@app.route('/admin/categories/add', methods=['POST'])
@admin_required
def add_category():
    nama_kategori = request.form['nama_kategori']
    
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO kategori (nama_kategori) VALUES (%s)", (nama_kategori,))
    mysql.connection.commit()
    
    flash('Kategori berhasil ditambahkan', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/admin/categories/delete/<int:category_id>', methods=['POST'])
@admin_required
def delete_category(category_id):
    cursor = mysql.connection.cursor()
    
    cursor.execute("SELECT COUNT(*) as total FROM buku WHERE id_kategori = %s", (category_id,))
    count = cursor.fetchone()['total']
    
    if count > 0:
        flash('Tidak dapat menghapus kategori yang masih memiliki buku', 'danger')
    else:
        cursor.execute("DELETE FROM kategori WHERE id_kategori = %s", (category_id,))
        mysql.connection.commit()
        flash('Kategori berhasil dihapus', 'success')
    
    return redirect(url_for('admin_categories'))

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    app.run(debug=True)
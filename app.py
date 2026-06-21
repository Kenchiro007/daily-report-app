from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DateField, SubmitField
from wtforms.validators import DataRequired, Length
from datetime import datetime, date, timedelta
import bcrypt
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///reports.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'กรุณาเข้าสู่ระบบก่อนใช้งาน'
login_manager.login_message_category = 'warning'

# ==================== Models ====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default='employee')
    department = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reports = db.relationship('Report', backref='user', lazy=True)
    
    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    report_date = db.Column(db.Date, default=date.today)
    work_done = db.Column(db.Text, nullable=False)
    issues = db.Column(db.Text)
    plan_tomorrow = db.Column(db.Text)
    status = db.Column(db.String(20), default='submitted')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.user.full_name if self.user else '',
            'report_date': self.report_date.isoformat(),
            'work_done': self.work_done,
            'issues': self.issues,
            'plan_tomorrow': self.plan_tomorrow,
            'status': self.status,
            'created_at': self.created_at.isoformat()
        }

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== Forms ====================
class ReportForm(FlaskForm):
    report_date = DateField('วันที่', default=date.today, validators=[DataRequired()])
    work_done = TextAreaField('งานที่ทำวันนี้', validators=[DataRequired(), Length(min=5)])
    issues = TextAreaField('ปัญหา/อุปสรรค')
    plan_tomorrow = TextAreaField('แผนงานพรุ่งนี้')
    submit = SubmitField('ส่งรายงาน')

class EditReportForm(FlaskForm):
    report_date = DateField('วันที่', validators=[DataRequired()])
    work_done = TextAreaField('งานที่ทำวันนี้', validators=[DataRequired()])
    issues = TextAreaField('ปัญหา/อุปสรรค')
    plan_tomorrow = TextAreaField('แผนงานพรุ่งนี้')
    status = SelectField('สถานะ', choices=[('draft', 'ร่าง'), ('submitted', 'ส่งแล้ว'), ('approved', 'อนุมัติ')])
    submit = SubmitField('บันทึก')

# ==================== Routes ====================

@app.route('/')
@login_required
def index():
    if current_user.role == 'manager':
        return redirect(url_for('dashboard'))
    return redirect(url_for('report_form'))

# -------- Authentication --------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash(f'ยินดีต้อนรับ {user.full_name}!', 'success')
            return redirect(url_for('index'))
        
        flash('ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('คุณออกจากระบบเรียบร้อย', 'info')
    return redirect(url_for('login'))

# -------- Employee Routes --------
@app.route('/report', methods=['GET', 'POST'])
@login_required
def report_form():
    if current_user.role == 'manager':
        flash('หัวหน้าไม่สามารถส่งรายงานได้', 'warning')
        return redirect(url_for('dashboard'))
    
    form = ReportForm()
    if form.validate_on_submit():
        report = Report(
            user_id=current_user.id,
            report_date=form.report_date.data,
            work_done=form.work_done.data,
            issues=form.issues.data,
            plan_tomorrow=form.plan_tomorrow.data,
            status='submitted'
        )
        db.session.add(report)
        db.session.commit()
        flash('ส่งรายงานสำเร็จ! ขอบคุณครับ 🙏', 'success')
        return redirect(url_for('my_reports'))
    
    return render_template('report_form.html', form=form)

@app.route('/my-reports')
@login_required
def my_reports():
    if current_user.role == 'manager':
        return redirect(url_for('dashboard'))
    
    reports = Report.query.filter_by(user_id=current_user.id).order_by(Report.report_date.desc(), Report.created_at.desc()).all()
    return render_template('my_reports.html', reports=reports)

@app.route('/edit-report/<int:report_id>', methods=['GET', 'POST'])
@login_required
def edit_report(report_id):
    report = Report.query.get_or_404(report_id)
    
    if report.user_id != current_user.id and current_user.role != 'manager':
        abort(403)
    
    if report.status == 'submitted' and current_user.role == 'employee':
        flash('ไม่สามารถแก้ไขรายงานที่ส่งแล้วได้', 'warning')
        return redirect(url_for('my_reports'))
    
    form = EditReportForm(obj=report)
    if form.validate_on_submit():
        report.report_date = form.report_date.data
        report.work_done = form.work_done.data
        report.issues = form.issues.data
        report.plan_tomorrow = form.plan_tomorrow.data
        report.status = form.status.data
        report.updated_at = datetime.utcnow()
        db.session.commit()
        flash('อัปเดตรายงานเรียบร้อย', 'success')
        if current_user.role == 'manager':
            return redirect(url_for('view_employee', user_id=report.user_id))
        return redirect(url_for('my_reports'))
    
    return render_template('edit_report.html', form=form, report=report)

# -------- Manager Routes --------
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'manager':
        flash('คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 'danger')
        return redirect(url_for('report_form'))
    
    total_reports = Report.query.count()
    today_reports = Report.query.filter(Report.report_date == date.today()).count()
    recent_reports = Report.query.order_by(Report.created_at.desc()).limit(20).all()
    
    from sqlalchemy import func
    user_stats = db.session.query(
        User.id, User.full_name, func.count(Report.id).label('count')
    ).outerjoin(Report).group_by(User.id).all()
    
    return render_template('dashboard.html', 
                         total_reports=total_reports,
                         today_reports=today_reports,
                         recent_reports=recent_reports,
                         user_stats=user_stats)

@app.route('/view-all-reports')
@login_required
def view_all_reports():
    if current_user.role != 'manager':
        abort(403)
    
    employee_id = request.args.get('employee_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    status = request.args.get('status')
    
    query = Report.query
    if employee_id:
        query = query.filter_by(user_id=employee_id)
    if date_from:
        query = query.filter(Report.report_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(Report.report_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
    if status:
        query = query.filter_by(status=status)
    
    reports = query.order_by(Report.report_date.desc(), Report.created_at.desc()).all()
    employees = User.query.filter_by(role='employee').all()
    
    return render_template('view_all_reports.html', reports=reports, employees=employees)

@app.route('/view-employee/<int:user_id>')
@login_required
def view_employee(user_id):
    if current_user.role != 'manager':
        abort(403)
    
    employee = User.query.get_or_404(user_id)
    reports = Report.query.filter_by(user_id=user_id).order_by(Report.report_date.desc(), Report.created_at.desc()).all()
    
    return render_template('view_employee.html', employee=employee, reports=reports)

@app.route('/delete-report/<int:report_id>', methods=['POST'])
@login_required
def delete_report(report_id):
    if current_user.role != 'manager':
        abort(403)
    
    report = Report.query.get_or_404(report_id)
    db.session.delete(report)
    db.session.commit()
    flash('ลบรายงานเรียบร้อย', 'success')
    return redirect(request.referrer or url_for('dashboard'))

# ==================== Main ====================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # สร้างผู้ใช้เริ่มต้น (ถ้ายังไม่มี)
        if not User.query.first():
            hashed_pw = bcrypt.hashpw('head123'.encode('utf-8'), bcrypt.gensalt())
            head = User(username='head', password=hashed_pw, full_name='หัวหน้าทีม', role='manager', department='IT')
            db.session.add(head)
            
            employees = [
                ('john', 'pass123', 'John Doe', 'Development'),
                ('jane', 'pass123', 'Jane Smith', 'Design'),
                ('bob', 'pass123', 'Bob Johnson', 'Development'),
                ('alice', 'pass123', 'Alice Brown', 'Marketing')
            ]
            for emp in employees:
                hashed = bcrypt.hashpw(emp[1].encode('utf-8'), bcrypt.gensalt())
                user = User(username=emp[0], password=hashed, full_name=emp[2], role='employee', department=emp[3])
                db.session.add(user)
            
            db.session.commit()
            print("✅ สร้างผู้ใช้เริ่มต้นเรียบร้อย!")
            print("📝 หัวหน้า: head / head123")
            print("📝 ลูกน้อง: john, jane, bob, alice / pass123")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
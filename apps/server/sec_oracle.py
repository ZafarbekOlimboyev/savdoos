import os,uuid,tempfile
os.environ["DATABASE_URL"]="sqlite:///"+os.path.join(tempfile.gettempdir(),"sec_"+uuid.uuid4().hex+".db").replace("\\","/")
os.environ["SECRET_KEY"]="s"; os.environ["VENDOR_ADMIN_KEY"]="K"
from app import initdb,seed; initdb.main(); seed.run()
from fastapi.testclient import TestClient; from app.main import app; c=TestClient(app)
from app.db.session import SessionLocal
from app.models.auth import Employee
from app.models.enums import EmployeeStatus

phone="+998901234567"

# baseline: active + correct
r0=c.post("/api/v1/auth/login/password",json={"phone":phone,"password":"demo1234"})
print("ACTIVE+correct:",r0.status_code, r0.json().get("access_token") is not None if r0.status_code==200 else r0.json())

# suspend the account in DB
db=SessionLocal()
e=db.query(Employee).filter(Employee.phone==phone, Employee.password_hash.isnot(None)).first()
print("emp found:",e.id if e else None,"status was",e.status if e else None)
e.status=EmployeeStatus.suspended
db.commit(); db.close()

# correct password on suspended
r1=c.post("/api/v1/auth/login/password",json={"phone":phone,"password":"demo1234"})
# wrong password on suspended
r2=c.post("/api/v1/auth/login/password",json={"phone":phone,"password":"WRONGpass999"})

print("SUSPENDED+correct:",r1.status_code,repr(r1.json().get("detail")))
print("SUSPENDED+wrong:  ",r2.status_code,repr(r2.json().get("detail")))
print("ORACLE (responses differ):", r1.json().get("detail")!=r2.json().get("detail"))

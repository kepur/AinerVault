from app.api.deps import get_db
from ainern2d_shared.ainer_db_models.system_models import User
db = next(get_db())
user = db.query(User).filter(User.email=="admin@ainer.com").first()
print(user.id)

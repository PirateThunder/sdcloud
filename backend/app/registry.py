def import_models() -> None:
    from .auth import models as _auth_models  # noqa: F401
    from .conversations import models as _conversation_models  # noqa: F401
    from .generations import models as _generation_models  # noqa: F401
    from .models import models as _model_models  # noqa: F401
    from .simulations import models as _simulation_models  # noqa: F401
    from .users import models as _user_models  # noqa: F401

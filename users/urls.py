from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'users'

urlpatterns = [
    path('signup/', views.SignupView.as_view(), name='signup'),
    path('login/', views.TelegramLoginView.as_view(), name='login'),
    path('kirish/parol/', views.UsernamePasswordLoginView.as_view(), name='login_password'),
    path('parol-ornatish/', views.SetPasswordView.as_view(), name='set_password'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('admin/', views.AdminPanelView.as_view(), name='admin_panel'),
]

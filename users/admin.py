from django.contrib import admin

from .models import TelegramContact


@admin.register(TelegramContact)
class TelegramContactAdmin(admin.ModelAdmin):
    list_display = (
        'telegram_id', 'username', 'first_name', 'last_name',
        'came_with_token', 'start_count', 'first_seen_at', 'last_seen_at',
    )
    list_filter = ('came_with_token', 'first_seen_at')
    search_fields = ('telegram_id', 'username', 'first_name', 'last_name')
    readonly_fields = ('first_seen_at', 'last_seen_at')
    ordering = ('-last_seen_at',)

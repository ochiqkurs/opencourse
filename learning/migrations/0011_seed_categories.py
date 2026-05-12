from django.db import migrations


CATEGORIES = [
    {
        "slug": "frontend",
        "name": "Frontend",
        "description": "Web sahifalarning ko'rinish qismi va brauzerda ishlovchi texnologiyalar.",
        "icon": "layout",
        "color": "sky",
        "order": 10,
    },
    {
        "slug": "backend",
        "name": "Backend",
        "description": "Server tomonidagi dasturlash, API va veb framework'lar.",
        "icon": "server",
        "color": "emerald",
        "order": 20,
    },
    {
        "slug": "mobil",
        "name": "Mobil dasturlash",
        "description": "iOS va Android uchun mobil ilovalar yaratish.",
        "icon": "smartphone",
        "color": "violet",
        "order": 30,
    },
    {
        "slug": "malumotlar-bazasi",
        "name": "Ma'lumotlar bazasi",
        "description": "SQL va NoSQL ma'lumotlar bazalari.",
        "icon": "database",
        "color": "amber",
        "order": 40,
    },
    {
        "slug": "devops-bulut",
        "name": "DevOps va Bulut",
        "description": "Server administratorlik, konteynerlar va bulutli xizmatlar.",
        "icon": "cloud",
        "color": "slate",
        "order": 50,
    },
    {
        "slug": "data-ai",
        "name": "Data Science va AI",
        "description": "Ma'lumotlar tahlili, sun'iy intellekt va mashina o'rganishi.",
        "icon": "brain-circuit",
        "color": "rose",
        "order": 60,
    },
    {
        "slug": "algoritmlar",
        "name": "Algoritmlar va tizim",
        "description": "Ma'lumotlar tuzilmasi, algoritmlar va tizim dizayni.",
        "icon": "code",
        "color": "indigo",
        "order": 70,
    },
    {
        "slug": "dizayn",
        "name": "Dizayn",
        "description": "UI/UX va vizual dizayn vositalari.",
        "icon": "palette",
        "color": "pink",
        "order": 80,
    },
]


COURSE_CATEGORY = {
    # Frontend
    "htmlda-dasturlash": "frontend",
    "css-asoslari": "frontend",
    "javascript-darslari": "frontend",
    "typescript": "frontend",
    "reactjs": "frontend",
    "vuejs": "frontend",
    "nextjs": "frontend",
    "redux": "frontend",
    "bootstrap": "frontend",
    "sass": "frontend",
    "react-firebase": "frontend",
    # Backend
    "pythonda-dasturlash-asoslari": "backend",
    "django-asoslari": "backend",
    "django-rest-framework": "backend",
    "fastapi": "backend",
    "nodejs": "backend",
    "expressjs": "backend",
    "php": "backend",
    "laravel": "backend",
    "spring-boot": "backend",
    "csharp-dotnet-asoslari": "backend",
    "go-golang": "backend",
    "java": "backend",
    "telegram-bot-aiogram": "backend",
    "graphql": "backend",
    "prisma-orm": "backend",
    # Mobile
    "flutter": "mobil",
    "react-native": "mobil",
    "swift-asoslari": "mobil",
    "swiftui": "mobil",
    "android-kotlin": "mobil",
    "dart-tili": "mobil",
    # Databases
    "postgresql-darslari-pgadminda": "malumotlar-bazasi",
    "postgresql-darslari-terminalda": "malumotlar-bazasi",
    "mongodb-va-mongoose": "malumotlar-bazasi",
    "mysql": "malumotlar-bazasi",
    # DevOps & Cloud
    "docker": "devops-bulut",
    "nginx-asoslari": "devops-bulut",
    "linux-ubuntu-asoslari": "devops-bulut",
    "linux-administratorligi": "devops-bulut",
    "github": "devops-bulut",
    "bulutli-texnologiyalar": "devops-bulut",
    "tarmoq-administratori": "devops-bulut",
    # Data Science & AI
    "numpy": "data-ai",
    "pandas": "data-ai",
    "machine-learning-nazariyasi": "data-ai",
    "kompyuter-korishi-deep-learning": "data-ai",
    "ai-agentlar-qurish-kursi": "data-ai",
    # Algorithms & System
    "dsa-in-python-and-js": "algoritmlar",
    "tizim-dizayni": "algoritmlar",
    # Design
    "figma": "dizayn",
}


def seed_categories(apps, schema_editor):
    Category = apps.get_model("learning", "Category")
    Course = apps.get_model("learning", "Course")

    slug_to_id = {}
    for cat in CATEGORIES:
        obj, _ = Category.objects.update_or_create(
            slug=cat["slug"],
            defaults={
                "name": cat["name"],
                "description": cat["description"],
                "icon": cat["icon"],
                "color": cat["color"],
                "order": cat["order"],
            },
        )
        slug_to_id[cat["slug"]] = obj.id

    for course_slug, cat_slug in COURSE_CATEGORY.items():
        Course.objects.filter(slug=course_slug).update(
            category_id=slug_to_id[cat_slug]
        )


def unseed_categories(apps, schema_editor):
    Category = apps.get_model("learning", "Category")
    Course = apps.get_model("learning", "Course")

    Course.objects.filter(
        category__slug__in=[c["slug"] for c in CATEGORIES]
    ).update(category=None)
    Category.objects.filter(
        slug__in=[c["slug"] for c in CATEGORIES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0010_remove_videosession_lesson_remove_videosession_user_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
    ]

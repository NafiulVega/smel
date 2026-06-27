from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom User model — saat ini identik dengan AbstractUser bawaan Django.
    Diperlukan agar bisa dikustomisasi di masa depan tanpa perlu migrasi besar.
    """

    class Meta:
        db_table = 'user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.username

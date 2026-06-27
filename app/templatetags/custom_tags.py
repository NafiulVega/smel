from django import template
from django.urls import resolve

register = template.Library()

@register.simple_tag
def active(request, pattern):
    return 'active' if resolve(request.path_info).url_name == pattern else ''

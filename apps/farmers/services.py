from .models import Farmer


def search_farmers(query):
    return Farmer.objects.filter(last_name__icontains=query) | Farmer.objects.filter(first_name__icontains=query)

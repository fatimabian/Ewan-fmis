from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import AdminRequiredMixin
from .forms import ServiceCatalogForm
from .models import ServiceCatalog


class CatalogListView(FMISLoginRequiredMixin, AdminRequiredMixin, ListView):
    model = ServiceCatalog
    template_name = "service_catalog/list.html"

    def get_queryset(self):
        queryset = ServiceCatalog.objects.all()
        query = self.request.GET.get("q", "").strip()
        category = self.request.GET.get("category", "").strip()
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(code__icontains=query))
        if category:
            queryset = queryset.filter(category=category)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = ServiceCatalog.objects.values_list("category", flat=True).distinct().order_by("category")
        context["selected_category"] = self.request.GET.get("category", "")
        context["query"] = self.request.GET.get("q", "")
        return context


class CatalogCreateView(FMISLoginRequiredMixin, AdminRequiredMixin, CreateView):
    form_class = ServiceCatalogForm
    template_name = "service_catalog/form.html"
    success_url = reverse_lazy("service_catalog:list")

    def form_valid(self, form):
        if not form.instance.code:
            next_number = ServiceCatalog.objects.count() + 1
            form.instance.code = f"SC-{next_number:02d}"
            while ServiceCatalog.objects.filter(code=form.instance.code).exists():
                next_number += 1
                form.instance.code = f"SC-{next_number:02d}"
        form.instance.is_active = not bool(self.request.POST.get("draft"))
        messages.success(self.request, "Service catalog item created.")
        return super().form_valid(form)


class CatalogUpdateView(FMISLoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = ServiceCatalog
    form_class = ServiceCatalogForm
    template_name = "service_catalog/form.html"
    success_url = reverse_lazy("service_catalog:list")

    def form_valid(self, form):
        form.instance.is_active = not bool(self.request.POST.get("draft"))
        messages.success(self.request, "Service catalog item updated.")
        return super().form_valid(form)


class CatalogDeleteView(FMISLoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = ServiceCatalog
    success_url = reverse_lazy("service_catalog:list")

    def form_valid(self, form):
        messages.success(self.request, "Service catalog item deleted.")
        return super().form_valid(form)

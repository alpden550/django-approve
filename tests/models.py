from django.db import models


class Sample(models.Model):
    name = models.CharField(max_length=50)
    amount = models.IntegerField()
    owner = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    readonly = models.IntegerField(editable=False, default=0)
    attachment = models.FileField(upload_to="files/")
    tags = models.ManyToManyField("auth.Group")

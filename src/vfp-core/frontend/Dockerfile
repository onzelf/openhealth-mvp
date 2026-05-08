FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY openhealth_logo.avif /usr/share/nginx/html/openhealth_logo.avif

EXPOSE 80
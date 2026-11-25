#!/bin/sh
cd "$(dirname "$0")" || exit

node scripts/check-package-installed.js postcss sass autoprefixer || exit

build_style() {
  echo "Creating $1 style..."
  cp resources/vars-$1.scss resources/vars.scss
  npx sass resources:sass_processed
  npx postcss \
      sass_processed/ace-dmoj.css \
      sass_processed/featherlight.css \
      sass_processed/martor-description.css \
      sass_processed/select2-dmoj.css \
      sass_processed/style.css \
      sass_processed/blog-modern.css \
      sass_processed/blog-post.css \
      sass_processed/theme-toggle.css \
      --verbose --use autoprefixer -d "$2"
  rm resources/vars.scss
}

build_style 'default' 'resources'
build_style 'dark' 'resources/dark'

# CBNoj "paper" interface: loaded only when the cbn_ui cookie / CBN_UI_DEFAULT is on (see templates/base.html).
echo "Creating cbn theme..."
npx sass --no-source-map resources/cbn-theme.scss sass_processed/cbn-theme.css
npx postcss sass_processed/cbn-theme.css --no-map --use autoprefixer -o resources/cbn-theme.css

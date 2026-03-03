# Maintainer: crinderneck <cjrinderneck@protonmail.com>
pkgname=nws-weather-tui
pkgver=0.1.0
pkgrel=1
pkgdesc="A terminal-based weather application for the US, powered by the National Weather Service API"
arch=('any')
url="https://github.com/crinderneck/nws-weather-tui"
license=('MIT')
depends=(
    'python'
    'python-pillow'
    'python-requests'
)
optdepends=(
    'python-astral: sunrise/sunset and moonrise/moonset times'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
    'python-wheel'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}

# Maintainer: crinderneck <cjrinderneck@protonmail.com>
pkgname=nws-weather-tui
pkgver=0.2.1
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
    'python-numpy: faster radar decoding'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")
# After pushing the v$pkgver tag, run `updpkgsums` to fill this in (see RELEASING.md).
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

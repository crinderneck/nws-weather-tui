# Maintainer: crinderneck <cjrinderneck@protonmail.com>
pkgname=nws-weather-tui
pkgver=0.3.0
pkgrel=1
pkgdesc="A terminal-based weather application for the US, powered by the National Weather Service API"
arch=('any')
url="https://github.com/crinderneck/nws-weather-tui"
license=('MIT')
depends=(
    'python'
    'python-astral'
    'python-numpy'
    'python-pillow'
    'python-requests'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz")
# After pushing the v$pkgver tag, run `updpkgsums` to fill this in (see RELEASING.md).
sha256sums=('3edeb1645c339a26753bb3b33192ce2bdbcbd21934dd5e8feb0af4faaf2cc162')

build() {
    cd "$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}

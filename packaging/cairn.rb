# Scratch-tap proof formula for Cairn (vault to-do 6e9ef, 2026-08-04).
# Pinned to the Phase 1 merge commit on dev. The real release formula will
# point at a tagged release tarball; everything else carries over as-is.
class Cairn < Formula
  include Language::Python::Virtualenv

  desc "Deterministic Markdown-vault note CLI for a locked-down work Mac"
  homepage "https://github.com/kenschwartz/cairn"
  url "https://github.com/kenschwartz/cairn/archive/215f05ec97e2e15110e3196c52d4796a78492a3f.tar.gz"
  version "1.0.0"
  sha256 "daa6a1d843b8357da2335349e6a227fc37ea4cf847500bfbb13da6fb3baccd37"

  depends_on "python@3.14"

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    system bin/"cairn", "--help"
  end
end

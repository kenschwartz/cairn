# Canonical Homebrew formula for Cairn. This file makes the repository its
# own tap: `brew tap kenschwartz/cairn` then `brew install cairn`.
# Pinned to the v1.0.0 release tarball. Keep this the single source of truth
# for the brew package (do not maintain a second copy elsewhere).
class Cairn < Formula
  include Language::Python::Virtualenv

  desc "Deterministic Markdown-vault note CLI for a locked-down work Mac"
  homepage "https://github.com/kenschwartz/cairn"
  url "https://github.com/kenschwartz/cairn/archive/refs/tags/v1.0.1.tar.gz"
  sha256 "2475958aaf84ce1395e86dcb74f2b9c2f820700c813079292d673ab002f7be2b"
  license "MIT"
  head "https://github.com/kenschwartz/cairn.git", branch: "main"

  depends_on "python@3.14"

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "1.0.1", shell_output("#{bin}/cairn --version")
  end
end

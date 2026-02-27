class HledgerTextual < Formula
  include Language::Python::Virtualenv

  desc "Terminal user interface for hledger plain-text accounting"
  homepage "https://github.com/thesmokinator/hledger-textual"
  url "https://pypi.io/packages/source/h/hledger-textual/hledger_textual-0.1.0.tar.gz"
  sha256 "REPLACE_WITH_ACTUAL_SHA256_AFTER_FIRST_PUBLISH"
  license "MIT"

  depends_on "python@3.12"
  depends_on "hledger"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "usage:", shell_output("#{bin}/hledger-textual --help")
  end
end

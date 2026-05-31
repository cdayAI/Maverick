# Homebrew formula for Maverick (source of truth lives in the monorepo).
#
# To make it installable, this file is mirrored into a Homebrew *tap* repo
# named `homebrew-tap` under the project's account, so users run:
#
#     brew install cdayAI/tap/maverick
#
# The .github/workflows/homebrew-bump.yml action keeps the `url`/`sha256`
# current: on each `v*` release it resolves the published sdist from PyPI and
# opens a PR updating this file (and you sync it to the tap repo).
#
# It installs the published `maverick-agent` package plus the installer wizard
# into an isolated virtualenv, then links the `maverick` CLI onto the PATH.
class Maverick < Formula
  include Language::Python::Virtualenv

  desc "Open-source AI agent swarm that runs locally, works for hours, under a budget cap"
  homepage "https://github.com/cdayAI/Maverick"
  url "https://files.pythonhosted.org/packages/source/m/maverick-agent/maverick_agent-0.1.6.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000" # set by homebrew-bump.yml
  license "MIT"

  depends_on "python@3.12"

  def install
    # This is a personal *tap* (not homebrew-core), so we resolve the
    # dependency tree from PyPI into the venv at install time rather than
    # vendoring every transitive `resource` block by hand.
    virtualenv_create(libexec, "python3.12")
    system libexec/"bin/pip", "install", "maverick-agent[installer]==#{version}"
    bin.install_symlink Dir[libexec/"bin/maverick"]
  end

  test do
    # `maverick version` prints the installed package versions; assert this
    # formula's version shows up, proving the CLI installed and runs.
    assert_match version.to_s, shell_output("#{bin}/maverick version")
  end
end

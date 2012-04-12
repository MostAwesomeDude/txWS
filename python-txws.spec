%global modname txws

Name:             python-txws
Version:          0.7
Release:          2%{?dist}
Summary:          Twisted WebSockets wrapper

Group:            Development/Languages
License:          MIT
URL:              http://pypi.python.org/pypi/txWS
Source0:          http://pypi.python.org/packages/source/t/txWS/txWS-0.7.tar.gz

BuildArch:        noarch

BuildRequires:    python-devel
BuildRequires:    python-setuptools
BuildRequires:    python-twisted

Requires:         python-twisted

%description
txWS (pronounced "Twisted WebSockets") is a small, short, simple library
for adding WebSockets server support to your favorite Twisted applications.

%prep
%setup -q -n txWS-%{version}

%build
%{__python} setup.py build 

%install
%{__python} setup.py install -O1 --skip-build --root $RPM_BUILD_ROOT

# We could run the tests when building, but txWS doesn't ship the tests.py with
# the distribution.  Leaving it commented out as a possibility for later.
#%check
#PYTHONPATH=$(pwd) trial tests.py

%files
%defattr(-,root,root,-)
%doc README.rst

%{python_sitelib}/* 

%changelog
* Mon Apr 09 2012 Ralph Bean <rbean@redhat.com> 0.7-2
- Fixed spelling error in the specfile description.

* Thu Apr 05 2012 Ralph Bean <rbean@redhat.com>  0.7-1
- initial package for Fedora

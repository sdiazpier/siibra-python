# Copyright 2018-2020 Institute of Neuroscience and Medicine (INM-1), Forschungszentrum Jülich GmbH

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from .. import QUIET,__version__
from ..retrieval import GitlabConnector
from ..commons import logger,Registry

from .datasets import Dataset

import os
import re


# Until openminds is fully supported, we get configurations of siibra concepts from gitlab.
GITLAB_PROJECT_TAG=os.getenv("SIIBRA_CONFIG_GITLAB_PROJECT_TAG", "siibra-{}".format(__version__))

class SemanticConcept():
    """
    Parent class encapsulating commonalities of the basic siibra concept like atlas, parcellation, space, region.
    These concepts have an id, name, and key, and they are bootstrapped from metadata stored in an online resources.
    Typically, they are linked with one or more datasets that can be retrieved from the same or another online resource, 
    providing data files or additional metadata descriptions on request.
    """

    logger.debug(f"Configuration: {GITLAB_PROJECT_TAG}")
    uses_default_tag = not "SIIBRA_CONFIG_GITLAB_PROJECT_TAG" in os.environ
    _bootstrap_folder = None

    _BOOTSTRAP_CONNECTORS = ( 
        # we use an iterator to only instantiate the one[s] used
        GitlabConnector(
            'https://jugit.fz-juelich.de',3484,
            GITLAB_PROJECT_TAG,skip_branchtest=uses_default_tag),
        GitlabConnector(
            'https://gitlab.ebrains.eu',93,
            GITLAB_PROJECT_TAG,skip_branchtest=uses_default_tag),
    )
 
    def __init__(self,identifier,name,dataset_specs):
        self.id = identifier
        self.name = name
        self.key = __class__._create_key(name)
        # objects for datasets wil only be generated lazily on request
        self._dataset_specs = dataset_specs
        self._datasets_cached = None

    def _populate_datasets(self):
        self._datasets_cached = []
        for spec in self._dataset_specs:
            type_id = Dataset.extract_type_id(spec)
            Specialist = Dataset.REGISTRY.get(type_id,None)
            if Specialist is None:
                raise RuntimeError(f"No class available for building datasets with type {spec.get('@type',None)}. Candidates were {','.join(Dataset.REGISTRY.keys())}. Specification was: {spec}.")
            else:
                obj = Specialist._from_json(spec)
                logger.debug(f"Built {obj.__class__.__name__} object '{obj}' from dataset specification.")
                self._datasets_cached.append(obj)
                
    @property
    def datasets(self):
        if self._datasets_cached is None:
            self._populate_datasets()
        return self._datasets_cached

    def __init_subclass__(cls,type_id=None,bootstrap_folder=None):
        """
        This method is called whenever SiibraConcept gets subclassed 
        (see https://docs.python.org/3/reference/datamodel.html)
        """
        logger.debug(f"New subclass to {__class__.__name__}: {cls.__name__} (config folder: {bootstrap_folder})")
        cls.type_id = type_id
        if bootstrap_folder is not None:
            cls._bootstrap_folder=bootstrap_folder
        
    @staticmethod
    def provide_registry(cls):
        """ Used for decorating derived classes - will add a registry of bootstrapped instances then. """

        # find a suitable connector that is reachable
        for connector in cls._BOOTSTRAP_CONNECTORS:
            try:
                loaders = connector.get_loaders(cls._bootstrap_folder,'.json',progress=f"Bootstrap: {cls.__name__:15.15}")
                break                
            except Exception as e:
                print(str(e))
                logger.error(f"Cannot connect to configuration server {str(connector)}, trying a different mirror")
                raise(e)
        else:
            # we get here only if the loop is not broken
            raise RuntimeError(f"Cannot initialize atlases: No configuration data found for '{GITLAB_PROJECT_TAG}'.")

        cls.REGISTRY = Registry(matchfunc=cls.match_spec)
        with QUIET:
            for fname,loader in loaders:
                logger.info(f"Loading {fname}")
                obj = cls._from_json(loader.data)
                if isinstance(obj,cls):
                    cls.REGISTRY.add(obj.key,obj)
                else:
                    raise RuntimeError(f'Could not generate object of type {cls} from configuration {fname} - construction provided type {obj.__class__}')

        return cls
    
    @staticmethod
    def _create_key(name):
        """
        Creates an uppercase identifier string that includes only alphanumeric
        characters and underscore from a natural language name.
        """
        return re.sub(
                r' +','_',
                "".join([e if e.isalnum() else " " 
                    for e in name]).upper().strip() 
                )


    def __str__(self):
        return f"{self.__class__.__name__}: {self.name}"

    @property
    def volume_src(self):
        """
        The list of available datasets representing image volumes.
        """
        return [d for d in self.datasets if d.is_image_volume()]

    def get_volume_src(self, space ):
        """
        Get available volumes sources in the requested template space.

        Parameters
        ----------
        space : Space or str
            template space or template space specification

        Yields
        ------
        A list of volume sources
        """
        return [v for v in self.volume_src if v.space.matches(space)]

    def matches(self,spec):
        """
        Test if the given specification matches the name, key or id of the concept.
        """
        if isinstance(spec,self.__class__) and (spec==self):
            return True
        elif isinstance(spec,str):
            if spec==self.key:
                return True
            elif spec==self.id:
                return True
            else:
                # match the name
                words = [w for w in re.split('[ -]',spec)]
                squeezedname = self.name.lower().replace(" ","")
                return any([
                    all(w.lower() in squeezedname for w in words),
                    spec.replace(" ","") in squeezedname ])
        return False
    
    @classmethod
    def match_spec(cls,obj,spec):
        assert(isinstance(obj,cls))
        return obj.matches(spec)
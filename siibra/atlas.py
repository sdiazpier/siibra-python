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

from nibabel.affines import apply_affine
from numpy import linalg as npl
import numpy as np

from . import parcellations, spaces, features, logger
from .region import Region
from .features.regionprops import RegionProps
from .features.feature import GlobalFeature
from .features import classes as feature_classes
from .commons import create_key
from .config import ConfigurationRegistry
from .space import Space

class Atlas:

    def __init__(self,identifier,name):
        # Setup an empty. Use _add_space and _add_parcellation to complete
        # the setup.
        self.name = name
        self.id = identifier
        self.key = create_key(name)

        # no parcellation initialized at construction
        self.parcellations = [] # add with _add_parcellation
        self.spaces = [] # add with _add_space

        # nothing selected yet at construction 
        self.selected_region = None
        self.selected_parcellation = None 
        self.regionnames = None 

        # this can be set to prefer thresholded continuous maps as masks
        self._threshold_continuous_map = None

    def _add_space(self, space):
        self.spaces.append(space)

    def _add_parcellation(self, parcellation, select=False):
        self.parcellations.append(parcellation)
        if self.selected_parcellation is None or select:
            self.select_parcellation(parcellation)

    def __str__(self):
        return self.name

    @staticmethod
    def from_json(obj):
        """
        Provides an object hook for the json library to construct an Atlas
        object from a json stream.
        """
        if all([ '@id' in obj, 'spaces' in obj, 'parcellations' in obj,
            obj['@id'].startswith("juelich/iav/atlas/v1.0.0") ]):
            p = Atlas(obj['@id'], obj['name'])
            for space_id in obj['spaces']:
                assert(space_id in spaces)
                p._add_space( spaces[space_id] )
            for parcellation_id in obj['parcellations']:
                assert(parcellation_id in parcellations)
                p._add_parcellation( parcellations[parcellation_id] )
            return p
        return obj

    def select_parcellation(self, parcellation):
        """
        Select a different parcellation for the atlas.

        Parameters
        ----------

        parcellation : Parcellation
            The new parcellation to be selected
        """
        parcellation_obj = parcellations[parcellation]
        if parcellation_obj not in self.parcellations:
            logger.error('The requested parcellation is not supported by the selected atlas.')
            logger.error('    Parcellation:  '+parcellation_obj.name)
            logger.error('    Atlas:         '+self.name)
            logger.error(parcellation_obj.id,self.parcellations)
            raise Exception('Invalid Parcellation')
        self.selected_parcellation = parcellation_obj
        self.selected_region = parcellation_obj.regions
        self.regionnames = parcellation_obj.regionnames
        logger.info('Selected parcellation "{}"'.format(self.selected_parcellation))

    def get_maps(self, space : Space, tree : Region = None, force=False, resolution=None):
        """
        return the maps provided by the selected parcellation in the given space.
        This just forwards to the selected parcellation object.
        see Parcellation.get_maps()
        """
        return self.selected_parcellation.get_maps(space, tree, resolution, force)


    def get_mask(self, space : Space, force=False, resolution=None ):
        """
        Returns a binary mask  in the given space, where nonzero values denote
        voxels corresponding to the current region selection of the atlas. 

        WARNING: Note that for selections of subtrees of the region hierarchy, this
        might include holes if the leaf regions are not completly covering
        their parent and the parent itself has no label index in the map.

        Parameters
        ----------
        space : Space
            Template space 
        force : Boolean (default: False)
            if true, will start large downloads even if they exceed the download
            threshold set in the gbytes_feasible member variable (applies only
            to BigBrain space currently).
        resolution : float or None (Default: None)
            Request the template at a particular physical resolution. If None,
            the native resolution is used.
            Currently, this only works for the BigBrain volume.
        """
        return self.selected_parcellation.get_regionmask(
                space,
                self.selected_region,
                try_thres=self._threshold_continuous_map, 
                force=force, 
                resolution=resolution )

    def enable_continuous_map_thresholding(self,threshold):
        """
        Enables thresholding of continous maps with the given threshold as a
        preference of using region masks from the static parcellation. For
        example, when setting threshold to 0.2, the atlas will check if it
        finds a probability map for a selected region. If it does, it will use
        the thresholded probability map as a region mask for defining the
        region, and uses it e.g. for searching spatial features.

        Use with care, because a) continuous maps are not always available, and
        b) the value ranges of continuous maps are defined in different ways
        and require careful interpretation.
        """
        self._threshold_continuous_map = threshold

    def get_template(self, space, resolution=None, force=False ):
        """
        Get the volumetric reference template image for the given space.

        See
        ---
        Space.get_template()

        Parameters
        ----------
        space : str
            Template space definition, given as a dictionary with an '@id' key
        resolution : float or None (Default: None)
            Request the template at a particular physical resolution. If None,
            the native resolution is used.
            Currently, this only works for the BigBrain volume.
        force : Boolean (default: False)
            if true, will start large downloads even if they exceed the download
            threshold set in the gbytes_feasible member variable (applies only
            to BigBrain space currently).

        Yields
        ------
        A nibabel Nifti object representing the reference template, or None if not available.
        TODO Returning None is not ideal, requires to implement a test on the other side. 
        """
        if space not in self.spaces:
            logger.error('The selected atlas does not support the requested reference space.')
            logger.error('- Atlas: {}'.format(self.name))
            return None

        return space.get_template(resolution,force)

    def find(self,regionspec,all_parcellations=False):
        """
        Searches for regions in the selected parcellation.

        Parameters
        ----------
        regionspec : Region, string, or integer
            Any valid specification of a region object, could be a name, labelindex or region id.
        all_parcellations : Boolean (default:False)
            Do not only search the selected but instead all available parcellations.
        """
        if not all_parcellations:
            return self.selected_parcellation.find(regionspec)

        result = []
        for p in self.parcellations:
            result.extend(p.find(regionspec))
        return result


    def select_region(self,region):
        """
        Selects a particular region. 

        TODO test carefully for selections of branching points in the region
        hierarchy, then managing all regions under the tree. This is nontrivial
        because for incomplete parcellations, the union of all child regions
        might not represent the complete parent node in the hierarchy.

        Parameters
        ----------
        region : Region
            Region to be selected. Both a region object, as well as a region
            key (uppercase string identifier) are accepted.

        Yields
        ------
        True, if selection was successful, otherwise False.
        """
        previous_selection = self.selected_region
        if isinstance(region,Region):
            # argument is already a region object - use it
            self.selected_region = region
        else:
            # try to interpret argument as the key for a region 
            selected = self.selected_parcellation.regions.find(
                    region,select_uppermost=True)
            if len(selected)==1:
                # one match found - fine
                self.selected_region = next(iter(selected))
            elif len(selected)==0:
                # no match found
                logger.error('Cannot select region. The spec "{}" does not match any known region.'.format(region))
            else:
                # multiple matches found. Let's see if they represent a unique parent that we could select instead.
                parents = [r.parent for r in selected]
                if all([
                    parents.count(parents[0])==len(selected),
                    len(parents[0].children)==len(selected) ]):
                    self.selected_region = parents[0]
                    #logger.info('Selected parent region {}'.format(self.selected_region.name))
                else:
                    logger.error('Cannot select region. The spec "{}" is not unique. It matches: {}'.format(
                        region,", ".join([s.name for s in selected])))
        if not self.selected_region == previous_selection:
            logger.info('Selected region {}'.format(self.selected_region.name))
        return self.selected_region

    def clear_selection(self):
        """
        Cancels any current region selection.
        """
        self.select_region(self.selected_parcellation.regions)

    def region_selected(self,region):
        """
        Verifies wether a given region is part of the current selection.
        """
        return self.selected_region.includes(region)

    def coordinate_selected(self,space,coordinate):
        """
        Verifies wether a position in the given space is inside the current
        selection.

        Parameters
        ----------
        space : Space
            The template space in which the test shall be carried out
        coordinate : tuple x/y/z
            A coordinate position given in the physical space. It will be
            converted to the voxel space using the inverse affine matrix of the
            template space for the query.

        NOTE: since get_mask is lru-cached, this is not necessary slow
        """
        assert(space in self.spaces)
        # transform physical coordinates to voxel coordinates for the query
        mask = self.get_mask(space)
        voxel = (apply_affine(npl.inv(mask.affine),coordinate)+.5).astype(int)
        if np.any(voxel>=mask.dataobj.shape):
            return False
        if mask.dataobj[voxel[0],voxel[1],voxel[2]]==0:
            return False
        return True

    def get_features(self,modality,**kwargs):
        """
        Retrieve data features linked to the selected atlas configuration, by modality. 
        See siibra.features.modalities for available modalities.
        """
        hits = []

        if modality not in features.extractor_types.modalities:
            logger.error("Cannot query features - no feature extractor known "\
                    "for feature type {}.".format(modality))
            return hits

        # make sure that a region is selected when expected
        local_query = GlobalFeature not in feature_classes[modality].__bases__ 
        if local_query and not self.selected_region:
            logger.error("For non-global feature types "\
                    "select a region using 'select_region' to query data.")
            return hits

        for cls in features.extractor_types[modality]:
            if modality=='GeneExpression':
                extractor = cls(kwargs['gene'])
            else:
                extractor = cls()
            hits.extend(extractor.pick_selection(self))

        return hits

    def regionprops(self,space, include_children=False):
        """
        Extracts spatial properties of the currently selected region.
        Optionally, separate spatial properties of all child regions are
        computed.

        Parameters
        ----------
        space : Space
            The template space in which the spatial properties shall be
            computed.
        include_children : Boolean (default: False)
            If true, compute the properties of all children in the region
            hierarchy as well.

        Yields
        ------
        List of RegionProps objects (refer to RegionProp.regionname for
        identification of each)
        """
        result = []
        result.append ( RegionProps(self,space) )
        if include_children:
            parentregion = self.selected_region
            for region in self.selected_region.descendants:
                self.select_region(region)
                result.append ( RegionProps(self,space) )
            self.select_region(parentregion)
        return result



REGISTRY = ConfigurationRegistry('atlases', Atlas)

if __name__ == '__main__':

    atlas = REGISTRY.MULTILEVEL_HUMAN_ATLAS

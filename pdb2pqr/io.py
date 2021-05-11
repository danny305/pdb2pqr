"""Functions related to reading and writing data."""
import logging
import io

# import argparse
from collections import Counter
from pathlib import Path
from sys import path as sys_path
import gemmi 
from . import psize
from . import inputgen
from . import cif
from . import pdb
from . import definitions as defns
from .structures import Atom
from .config import FORCE_FIELDS, TITLE_STR
from .config import FILTER_WARNINGS_LIMIT, FILTER_WARNINGS
from .config import AA_DEF_PATH, NA_DEF_PATH, PATCH_DEF_PATH


_LOGGER = logging.getLogger(__name__)


class DuplicateFilter(logging.Filter):
    """Filter duplicate messages."""

    def __init__(self):
        super().__init__()
        self.warn_count = Counter()

    def filter(self, record):
        """Filter current record."""
        if record.levelname == "WARNING":
            for fwarn in FILTER_WARNINGS:
                if record.getMessage().startswith(fwarn):
                    self.warn_count.update([fwarn])
                    if self.warn_count[fwarn] > FILTER_WARNINGS_LIMIT:
                        return False
                    elif self.warn_count[fwarn] == FILTER_WARNINGS_LIMIT:
                        _LOGGER.warning(
                            f'Suppressing further "{fwarn}" messages'
                        )
                        return False
                    else:
                        return True
        return True


def print_biomolecule_atoms(atomlist, chainflag=False, pdbfile=False, ciffile=False):
    """Get PDB-format text lines for specified atoms.

    :param [Atom] atomlist:  the list of atoms to include
    :param bool chainflag:  flag whether to print chainid or not
    :return:  list of strings, each representing an atom PDB line
    :rtype:  [str]
    """

    if pdbfile and ciffile:
        raise ValueError('Cannot be both a pdb and cif file. Pick one.')
    text = []
    currentchain_id = None
    for iatom, atom in enumerate(atomlist):
        # Print the "TER" records between chains
        if currentchain_id is None:
            currentchain_id = atom.chain_id
        elif atom.chain_id != currentchain_id:
            currentchain_id = atom.chain_id
            text.append("TER\n")
        atom.serial = iatom + 1
        if pdbfile is True:
            text.append(f"{atom.get_pdb_string()}\n")
        elif ciffile is True:
            text.append(f"{atom.get_cif_string()}\n")
        else:
            text.append(f"{atom.get_pqr_string(chainflag=chainflag)}\n")
    if not ciffile:
        text.append("TER\nEND")
    return text


def get_old_header(pdblist):
    """Get old header from list of :mod:`pdb` objects.

    :param pdblist:  list of :mod:`pdb` block objects
    :type pdblist:  []
    :return:  old header as string
    :rtype:  str
    """
    old_header = io.StringIO()
    header_types = (
        pdb.HEADER,
        pdb.TITLE,
        pdb.COMPND,
        pdb.SOURCE,
        pdb.KEYWDS,
        pdb.EXPDTA,
        pdb.AUTHOR,
        pdb.REVDAT,
        pdb.JRNL,
        pdb.REMARK,
        pdb.SPRSDE,
        pdb.NUMMDL,
    )
    for pdb_obj in pdblist:
        if not isinstance(pdb_obj, header_types):
            break
        old_header.write(str(pdb_obj))
        old_header.write("\n")
    return old_header.getvalue()


def print_pqr_header(
    pdblist,
    atomlist,
    reslist,
    charge,
    force_field,
    ph_calc_method,
    ph,
    ffout,
    include_old_header=False,
):
    """Print the header for the PQR file.

    :param pdblist:  list of lines from original PDB with header
    :type pdblist:  [str]
    :param atomlist:  a list of atoms that were unable to have charges assigned
    :type atomlist:  [Atom]
    :param reslist:  a list of residues with non-integral charges
    :type reslist:  [Residue]
    :param charge:  the total charge on the biomolecule
    :type charge:  float
    :param force_field:  the forcefield name
    :type force_field:  str
    :param ph_calc_method:  pKa calculation method
    :type ph_calc_method:  str
    :param ph:  pH value, if any
    :type ph:  float
    :param ffout:  forcefield used for naming scheme
    :type ffout:  str
    :return:  the header for the PQR file
    :rtype:  str
    """
    if force_field is None:
        force_field = "User force field"
    else:
        force_field = force_field.upper()
    head = "\n".join(
        [
            "REMARK   1 PQR file generated by PDB2PQR",
            f"REMARK   1 {TITLE_STR}",
            "REMARK   1",
            f"REMARK   1 Forcefield Used: {force_field}",
            "",
        ]
    )
    if ffout is not None:
        head += f"REMARK   1 Naming Scheme Used: {ffout}\n"
    head += head + "REMARK   1\n"
    if ph_calc_method is not None:
        head += "\n".join(
            [
                f"REMARK   1 pKas calculated by {ph_calc_method} and "
                f"assigned using pH {ph:.2f}\n"
                "REMARK   1",
                "",
            ]
        )
    if len(atomlist) != 0:
        head += "\n".join(
            [
                "REMARK   5 WARNING: PDB2PQR was unable to assign charges",
                "REMARK   5 to the following atoms (omitted below):",
                "",
            ]
        )
        for atom in atomlist:
            head += f"REMARK   5    {atom.serial} {atom.name} in "
            head += f"{atom.residue.name} {atom.residue.res_seq}\n"
        head += "\n".join(
            [
                "REMARK   5 This is usually due to the fact that this residue "
                "is not",
                "REMARK   5 an amino acid or nucleic acid; or, there are no "
                "parameters",
                "REMARK   5 available for the specific protonation state of "
                "this",
                "REMARK   5 residue in the selected forcefield.",
                "REMARK   5",
                "",
            ]
        )
    if len(reslist) != 0:
        head += "\n".join(
            [
                "REMARK   5 WARNING: Non-integral net charges were found in",
                "REMARK   5 the following residues:",
                "",
            ]
        )
        for residue in reslist:
            head += f"REMARK   5    {residue} - "
            head += f"Residue Charge: {residue.charge:.4f}\n"
        head += "REMARK   5\n"
    head += "\n".join(
        [
            f"REMARK   6 Total charge on this biomolecule: {charge:.4f} e\n"
            "REMARK   6",
            "",
        ]
    )
    if include_old_header:
        head += "\n".join(
            ["REMARK   7 Original PDB header follows", "REMARK   7", ""]
        )
        head += get_old_header(pdblist)
    return head


def print_pqr_header_cif(
    atomlist,
    reslist,
    charge,
    force_field,
    ph_calc_method,
    ph,
    ffout,
    include_old_header=False,
):
    """Print the header for the PQR file in CIF format.

    :param atomlist:  a list of atoms that were unable to have charges assigned
    :type atomlist:  [Atom]
    :param reslist:  a list of residues with non-integral charges
    :type reslist:  [Residue]
    :param charge:  the total charge on the biomolecule
    :type charge:  float
    :param force_field:  the forcefield name
    :type force_field:  str
    :param ph_calc_method:  pKa calculation method
    :type ph_calc_method:  str
    :param ph:  pH value, if any
    :type ph:  float
    :param ffout:  forcefield used for naming scheme
    :type ffout:  str
    :return:  the header for the PQR file
    :rtype:  str
    """
    if force_field is None:
        force_field = "User force field"
    else:
        force_field = force_field.upper()

    header = "\n".join(
        [
            "#",
            "loop_",
            "_pdbx_database_remark.id",
            "_pdbx_database_remark.text",
            "1",
            ";",
            "PQR file generated by PDB2PQR",
            TITLE_STR,
            "",
            f"Forcefield used: {force_field}\n" "",
        ]
    )
    if ffout is not None:
        header += f"Naming scheme used: {ffout}\n"
    header += "\n"
    if ph_calc_method is not None:
        header += f"pKas calculated by {ph_calc_method} and "
        header += f"assigned using pH {ph:.2f}\n"
    header += "\n".join([";", "2", ";", ""])
    if len(atomlist) > 0:
        header += "\n".join(
            [
                "Warning: PDB2PQR was unable to assign charges",
                "to the following atoms (omitted below):",
                "",
            ]
        )
        for atom in atomlist:
            header += f"    {atom.serial} {atom.name} in "
            header += f"{atom.residue.name} {atom.residue.res_seq}\n"
        header += "\n".join(
            [
                "This is usually due to the fact that this residue is not",
                "an amino acid or nucleic acid; or, there are no parameters",
                "available for the specific protonation state of this",
                "residue in the selected forcefield.",
                "",
            ]
        )
    if len(reslist) > 0:
        header += "\n".join(
            [
                "Warning: Non-integral net charges were found in",
                "the following residues:",
                "",
            ]
        )
        for residue in reslist:
            header += f"    {residue} - "
            header += f"Residue Charge: {residue.charge:.4f}\n"
    header += "\n".join(
        [
            ";",
            "3",
            ";",
            f"Total charge on this biomolecule: {charge:.4f} e" ";",
            "",
        ]
    )
    if include_old_header:
        _LOGGER.warning("Including original CIF header not implemented.")
    header += "\n".join(
        [
            "#",
            "loop_",
            "_atom_site.group_PDB",
            "_atom_site.id",
            "_atom_site.label_atom_id",
            "_atom_site.label_comp_id",
            "_atom_site.label_seq_id",
            "_atom_site.Cartn_x",
            "_atom_site.Cartn_y",
            "_atom_site.Cartn_z",
            "_atom_site.pqr_partial_charge",
            "_atom_site.pqr_radius",
            "",
        ]
    )
    return header


def dump_apbs(output_pqr, output_path):
    """Generate and dump APBS input files related to output_pqr.

    :param output_pqr:  path to PQR file used to generate APBS input file
    :type output_pqr:  str
    :param output_path:  path for APBS input file output
    :type output_path:  str
    """
    method = "mg-auto"
    size = psize.Psize()
    size.parse_input(output_pqr)
    size.run_psize(output_pqr)
    input_ = inputgen.Input(output_pqr, size, method, 0, potdx=True)
    input_.print_input_files(output_path)


def test_for_file(name, type_):
    """Test for the existence of a file with a few name permutations.

    :param name:  name of file
    :type name:  str
    :param type_:  type of file
    :type type_:  str
    :return:  path to file
    :raises FileNotFoundError:  if file not found
    :rtype:  Path
    """
    if name is None:
        return ""
    test_names = [name, name.upper(), name.lower()]
    test_suffixes = ["", f".{type_.upper()}", f".{type_.lower()}"]
    test_dirs = [
        Path(p).joinpath("pdb2pqr", "dat") for p in sys_path + [Path.cwd()]
    ]
    if name.lower() in FORCE_FIELDS:
        name = name.upper()
    for test_dir in test_dirs:
        test_dir = Path(test_dir)
        for test_name in test_names:
            for test_suffix in test_suffixes:
                test_path = test_dir / (test_name + test_suffix)
                if test_path.is_file():
                    _LOGGER.debug(f"Found {type_} file {test_path}")
                    return test_path
    err = f"Unable to find {type_} file for {name}"
    raise FileNotFoundError(err)


def test_names_file(name):
    """Test for the .names file that contains the XML mapping.

    :param name:  the name of the forcefield
    :type name:  str
    :returns:  the path to the file
    :rtype:  Path
    :raises FileNotFoundError:  file not found
    """
    return test_for_file(name, "NAMES")


def test_dat_file(name):
    """Test for the forcefield file with a few name permutations.

    :param name:  the name of the dat file
    :type name:  str
    :returns:  the path to the file
    :rtype:  Path
    :raises FileNotFoundError:  file not found
    """
    return test_for_file(name, "DAT")


def test_xml_file(name):
    """Test for the XML file with a few name permutations.

    :param name:  the name of the dat file
    :type name:  str
    :returns:  the path to the file
    :rtype:  Path
    :raises FileNotFoundError:  file not found
    """
    return test_for_file(name, "xml")


def get_pdb_file(name):
    """Obtain a PDB file.

    First check the path given on the command line - if that file is not
    available, obtain the file from the PDB webserver at
    http://www.rcsb.org/pdb/

    .. todo::  This should be a context manager (to close the open file).
    .. todo::  Remove hard-coded parameters.

    :param name:  name of PDB file (path) or PDB ID
    :type name:  str
    :return:  file-like object containing PDB file
    :rtype:  file
    """
    path = Path(name)
    if path.is_file():
        return open(path, "rt", encoding="utf-8")
    else:
        url_path = f"https://files.rcsb.org/download/{path.stem}.pdb"
        _LOGGER.debug(f"Attempting to fetch PDB from {url_path}")
        resp = requests.get(url_path)
        if resp.status_code != 200:
            errstr = f"Got code {resp.status_code} while retrieving {url_path}"
            raise IOError(errstr)
        return io.StringIO(resp.text)


def get_molecule(input_path):
    """Get molecular structure information as a series of parsed lines.

    :param input_path:  structure file PDB ID or path
    :type intput_path:  str
    :return: (list of molecule records, Boolean indicating whether entry is
        CIF)
    :rtype:  ([str], bool)
    :raises RuntimeError:  problems with structure file
    """
    path = Path(input_path)
    input_file = get_pdb_file(input_path)
    is_cif = False
    if path.suffix.lower() == ".cif":
        pdblist, errlist = cif.read_cif(input_file)
        is_cif = True
    else:
        pdblist, errlist = pdb.read_pdb(input_file)
    if len(pdblist) == 0 and len(errlist) == 0:
        raise RuntimeError(f"Unable to find file {path}!")
    if len(errlist) != 0:
        if is_cif:
            _LOGGER.warning(f"Warning: {path} is a non-standard CIF file.\n")
        else:
            _LOGGER.warning(f"Warning: {path} is a non-standard PDB file.\n")
        _LOGGER.error(errlist)
    return pdblist, is_cif


def get_definitions(
    aa_path=AA_DEF_PATH, na_path=NA_DEF_PATH, patch_path=PATCH_DEF_PATH
):
    """Load topology definition files.

    :param aa_path:  likely location of amino acid topology definitions
    :type aa_path:  str
    :param na_path:  likely location of nucleic acid topology definitions
    :type na_path:  str
    :param patch_path:  likely location of patch topology definitions
    :type patch_path:  str
    :return:  topology Definitions object.
    :rtype:  Definition
    """
    aa_path_ = test_xml_file(aa_path)
    na_path_ = test_xml_file(na_path)
    patch_path_ = test_xml_file(patch_path)
    with open(aa_path_, "rt") as aa_file:
        with open(na_path_, "rt") as na_file:
            with open(patch_path_, "rt") as patch_file:
                definitions = defns.Definition(
                    aa_file=aa_file, na_file=na_file, patch_file=patch_file
                )
    return definitions


def setup_logger(output_pqr, level="DEBUG"):
    """Setup the logger.

    Setup logger to output the log file to the same directory as PQR
    output.

    :param str output_pqr:  path to PQR file
    :param str level:  logging level
    """
    # Get the output logging location
    output_pth = Path(output_pqr)
    log_file = Path(output_pth.parent, output_pth.stem + ".log")
    _LOGGER.info(f"Logs stored: {log_file}")
    logging.basicConfig(
        filename=log_file,
        format="%(asctime)s %(levelname)s:%(filename)s:%(lineno)d:%(funcName)s:%(message)s",
        level=getattr(logging, level),
    )
    console = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s:%(message)s")
    console.setFormatter(formatter)
    console.setLevel(level=getattr(logging, level))
    logging.getLogger("").addHandler(console)
    logging.getLogger("").addFilter(DuplicateFilter())


def read_pqr(pqr_file):
    """Read PQR file.

    :param pqr_file:  file object ready for reading as text
    :type pqr_file:  file
    :returns:  list of atoms read from file
    :rtype:  [Atom]
    """
    atoms = []
    for line in pqr_file:
        atom = Atom.from_pqr_line(line)
        if atom is not None:
            atoms.append(atom)
    return atoms


def read_qcd(qcd_file):
    """Read QCD (UHDB QCARD format) file.

    :param file qcd_file:  file object ready for reading as text
    :returns:  list of atoms read from file
    :rtype:  [Atom]
    """
    atoms = []
    atom_serial = 1
    for line in qcd_file:
        atom = Atom.from_qcd_line(line, atom_serial)
        if atom is not None:
            atoms.append(atom)
            atom_serial += 1
    return atoms


def read_dx(dx_file):
    """Read DX-format volumetric information.

    The OpenDX file format is defined at
    <https://www.idvbook.com/wp-content/uploads/2010/12/opendx.pdf`.

    .. note:: This function is not a general-format OpenDX file parser and
       makes many assumptions about the input data type, grid structure, etc.

    .. todo:: This function should be moved into the APBS code base.

    :param dx_file:  file object for DX file, ready for reading as text
    :type dx_file:  file
    :returns:  dictionary with data from DX file
    :rtype:  dict
    :raises ValueError:  on parsing error
    """
    dx_dict = {
        "grid spacing": [],
        "values": [],
        "number of grid points": None,
        "lower left corner": None,
    }
    for line in dx_file:
        words = [w.strip() for w in line.split()]
        if words[0] in ["#", "attribute", "component"]:
            pass
        elif words[0] == "object":
            if words[1] == "1":
                dx_dict["number of grid points"] = (
                    int(words[5]),
                    int(words[6]),
                    int(words[7]),
                )
        elif words[0] == "origin":
            dx_dict["lower left corner"] = [
                float(words[1]),
                float(words[2]),
                float(words[3]),
            ]
        elif words[0] == "delta":
            spacing = [float(words[1]), float(words[2]), float(words[3])]
            dx_dict["grid spacing"].append(spacing)
        else:
            for word in words:
                dx_dict["values"].append(float(word))
    return dx_dict


def write_cube(cube_file, data_dict, atom_list, comment="CPMD CUBE FILE."):
    """Write a Cube-format data file.

    Cube file format is defined at
    <https://docs.chemaxon.com/display/Gaussian_Cube_format.html>.

    .. todo:: This function should be moved into the APBS code base.

    :param cube_file:  file object ready for writing text data
    :type cube_file:  file
    :param data_dict:  dictionary of volumetric data as produced by
        :func:`read_dx`
    :type data_dict:  dict
    :param comment:  comment for Cube file
    :type comment:  str
    """
    cube_file.write(comment + "\n")
    cube_file.write("OUTER LOOP: X, MIDDLE LOOP: Y, INNER LOOP: Z\n")
    num_atoms = len(atom_list)
    origin = data_dict["lower left corner"]
    cube_file.write(
        f"{num_atoms:>4} {origin[0]:>11.6f} {origin[1]:>11.6f} "
        f"{origin[2]:>11.6f}\n"
    )
    num_points = data_dict["number of grid points"]
    spacings = data_dict["grid spacing"]
    for i in range(3):
        cube_file.write(
            f"{-num_points[i]:>4} "
            f"{spacings[i][0]:>11.6f} "
            f"{spacings[i][1]:>11.6f} "
            f"{spacings[i][2]:>11.6f}\n"
        )
    for atom in atom_list:
        cube_file.write(
            f"{atom.serial:>4} {atom.charge:>11.6f} {atom.x:>11.6f} "
            f"{atom.y:>11.6f} {atom.z:>11.6f}\n"
        )
    stride = 6
    values = data_dict["values"]
    for i in range(0, len(values), 6):
        if i + stride < len(values):
            imax = i + 6
            words = [f"{val:< 13.5E}" for val in values[i:imax]]
            cube_file.write(" ".join(words) + "\n")
        else:
            words = [f"{val:< 13.5E}" for val in values[i:]]
            cube_file.write(" ".join(words))


def print_pqr(args, pqr_lines, header_lines, missing_lines, is_cif):
    """Print PQR-format output to specified file

    :param argparse.Namespace args:  command-line arguments
    :param [str] pqr_lines:  output lines (records)
    :param [str] header_lines:  header lines
    :param [str] missing_lines:  lines describing missing atoms (should go
        in header)
    :param bool is_cif:  flag indicating CIF format
    """
    with open(args.output_pqr, "wt") as outfile:
        # Adding whitespaces if --whitespace is in the options
        if header_lines:
            _LOGGER.warning(
                f"Ignoring {len(header_lines)} header lines in output."
            )
        if missing_lines:
            _LOGGER.warning(
                f"Ignoring {len(missing_lines)} missing lines in output."
            )
        for line in pqr_lines:
            if args.whitespace:
                if line[0:4] == "ATOM" or line[0:6] == "HETATM":
                    newline = (
                        line[0:6]
                        + " "
                        + line[6:16]
                        + " "
                        + line[16:38]
                        + " "
                        + line[38:46]
                        + " "
                        + line[46:]
                    )
                    outfile.write(newline)
            else:
                if is_cif:
                    line = [col if col != "_" else "." for col in line.split()]
                    line = " ".join(line) + "\n"
                if line[0:3] != "TER" or not is_cif:
                    outfile.write(line)
        if is_cif:
            outfile.write("#\n")


def print_pdb(args, pdb_lines, header_lines, missing_lines, is_cif):
    """Print PDB-format output to specified file

    :param argparse.Namespace args:  command-line arguments
    :param [str]] pdb_lines:  output lines (records)
    :param [str] header_lines:  header lines
    :param [str] missing_lines:  lines describing missing atoms (should go in
        header)
    :param bool is_cif:  flag indicating CIF format
    """
    with open(args.pdb_output, "wt") as outfile:
        # Adding whitespaces if --whitespace is in the options
        if header_lines:
            _LOGGER.warning(
                f"Ignoring {len(header_lines)} header lines in output."
            )
        if missing_lines:
            _LOGGER.warning(
                f"Ignoring {len(missing_lines)} missing lines in output."
            )
        for line in pdb_lines:
            if is_cif:
                line = [col if col != "_" else "." for col in line.split()]
                line = " ".join(line) + "\n"
            if line[0:3] != "TER" or not is_cif:
                outfile.write(line)

def generate_atom_site_columns(pdb_lines):

    col_idx = {
        'group_PDB': 0, 
        'id': 1,
        'type_symbol': 2,

        'label_atom_id': 19,    # Not using label_atom_id; just auth_atom_id
        'label_alt_id': 4, 
        'label_comp_id': 5,
        'label_asym_id': 6, 
        'label_entity_id': 7, 
        'label_seq_id': 8, 

        'pdbx_PDB_ins_code': 9,
        
        'Cartn_x': 10,
        'Cartn_y': 11,
        'Cartn_z': 12,

        'occupancy': 13,
        'B_iso_or_equiv': 14,
        'pdbx_formal_charge': 15, # this will not be added to the file should be set to '?'

        'auth_seq_id': 16,
        'auth_comp_id': 17, 
        'auth_asym_id': 18,
        'auth_atom_id': 19,

        'pdbx_PDB_model_num': 20, 
    }

    group_PDB, id_, type_symbol = [], [], []
    label_atom_id, label_alt_id, label_comp_id = [], [], []
    label_asym_id, label_entity_id, label_seq_id = [], [], []
    pdbx_PDB_ins_code = []
    Cartn_x, Cartn_y, Cartn_z = [], [], []
    occupancy, B_iso_or_equiv, pdbx_formal_charge = [], [], []
    auth_seq_id, auth_comp_id, auth_asym_id, auth_atom_id = [], [], [], []
    pdbx_PDB_model_num = []

#     # TODO assert len(line.split()) 2 lengths allowed - with pqr and radii and without it. 

    for line in pdb_lines:
        line = line.split()

        # 23: no partial_charge and radii columns
        # 25: includes partial_charge and radii_columns
        if not len(line) in [23, 25]:
            continue

        group_PDB.append(line[col_idx['group_PDB']])
        id_.append(line[col_idx['id']])
        type_symbol.append(line[col_idx['type_symbol']])

        label_atom_id.append(line[col_idx['label_atom_id']])
        label_alt_id.append(line[col_idx['label_alt_id']])
        label_comp_id.append(line[col_idx['label_comp_id']])

        label_asym_id.append(line[col_idx['label_asym_id']]) 
        label_entity_id.append(line[col_idx['label_entity_id']])
        label_seq_id.append(line[col_idx['label_seq_id']]) 

        pdbx_PDB_ins_code.append(line[col_idx['pdbx_PDB_ins_code']])

        Cartn_x.append(line[col_idx['Cartn_x']])
        Cartn_y.append(line[col_idx['Cartn_y']])
        Cartn_z.append(line[col_idx['Cartn_z']])

        occupancy.append(line[col_idx['occupancy']])
        B_iso_or_equiv.append(line[col_idx['B_iso_or_equiv']])
        pdbx_formal_charge.append(line[col_idx['pdbx_formal_charge']])

        auth_seq_id.append(line[col_idx['auth_seq_id']])        
        auth_comp_id.append(line[col_idx['auth_comp_id']])
        auth_asym_id.append(line[col_idx['auth_asym_id']])
        auth_atom_id.append(line[col_idx['auth_atom_id']])

        pdbx_PDB_model_num.append(line[col_idx['pdbx_PDB_model_num']])


    return (
        group_PDB, id_, type_symbol, label_atom_id, label_alt_id, label_comp_id, 
        label_asym_id, label_entity_id, label_seq_id, pdbx_PDB_ins_code, 
        Cartn_x, Cartn_y, Cartn_z, occupancy, B_iso_or_equiv, pdbx_formal_charge, 
        auth_seq_id, auth_comp_id, auth_asym_id, auth_atom_id, pdbx_PDB_model_num
    )

       




def print_cif(args, pqr_lines, header_lines, missing_lines):

    doc = gemmi.cif.read_file(args.input_path)

    block = doc.sole_block()

    table = block.find_mmcif_category("_atom_site.")

    new_cols = generate_atom_site_columns(pqr_lines)

    loop = table.loop

    loop.set_all_values(new_cols)

    doc.write_file(args.output_pqr + ".gemmi", gemmi.cif.Style.Pdbx)
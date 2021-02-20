# -*- encoding: utf-8 -*-
"""
keri.core.coring module

"""
import re
import json
import copy

from dataclasses import dataclass, astuple
from collections import namedtuple, deque
from base64 import urlsafe_b64encode as encodeB64
from base64 import urlsafe_b64decode as decodeB64
from math import ceil
from fractions import Fraction
from orderedset import OrderedSet

import cbor2 as cbor
import msgpack
import pysodium
import blake3
import hashlib


from ..kering import (ValidationError, VersionError, EmptyMaterialError,
                      DerivationError, ShortageError)
from ..kering import Versionage, Version
from ..help.helping import extractValues

Serialage = namedtuple("Serialage", 'json mgpk cbor')

Serials = Serialage(json='JSON', mgpk='MGPK', cbor='CBOR')

Mimes = Serialage(json='application/keri+json',
                  mgpk='application/keri+msgpack',
                  cbor='application/keri+cbor',)

VERRAWSIZE = 6  # hex characters in raw serialization size in version string
# "{:0{}x}".format(300, 6)  # make num char in hex a variable
# '00012c'
VERFMT = "KERI{:x}{:x}{}{:0{}x}_"  #  version format string
VERFULLSIZE = 17  # number of characters in full versions string

def Versify(version=None, kind=Serials.json, size=0):
    """
    Return version string
    """
    if kind not in Serials:
        raise  ValueError("Invalid serialization kind = {}".format(kind))
    version = version if version else Version
    return VERFMT.format(version[0], version[1], kind, size, VERRAWSIZE)

Vstrings = Serialage(json=Versify(kind=Serials.json, size=0),
                     mgpk=Versify(kind=Serials.mgpk, size=0),
                     cbor=Versify(kind=Serials.cbor, size=0))


VEREX = b'KERI(?P<major>[0-9a-f])(?P<minor>[0-9a-f])(?P<kind>[A-Z]{4})(?P<size>[0-9a-f]{6})_'
Rever = re.compile(VEREX) #compile is faster
MINSNIFFSIZE = 12 + VERFULLSIZE  # min bytes in buffer to sniff else need more

def Deversify(vs):
    """
    Returns tuple(kind, version, size)
      Where:
        kind is serialization kind, one of Serials
                   json='JSON', mgpk='MGPK', cbor='CBOR'
        version is version tuple of type Version
        size is int of raw size

    Parameters:
      vs is version string str

    Uses regex match to extract:
        serialization kind
        keri version
        serialization size
    """
    match = Rever.match(vs.encode("utf-8"))  #  match takes bytes
    if match:
        major, minor, kind, size = match.group("major", "minor", "kind", "size")
        version = Versionage(major=int(major, 16), minor=int(minor, 16))
        kind = kind.decode("utf-8")
        if kind not in Serials:
            raise ValueError("Invalid serialization kind = {}".format(kind))
        size = int(size, 16)
        return(kind, version, size)

    raise ValueError("Invalid version string = {}".format(vs))

Ilkage = namedtuple("Ilkage", 'icp rot ixn dip drt rct vrc')  # Event ilk (type of event)

Ilks = Ilkage(icp='icp', rot='rot', ixn='ixn', dip='dip', drt='drt', rct='rct',
              vrc='vrc')

@dataclass(frozen=True)
class CrySelectCodex:
    """
    Select codex of selector characters for cyptographic material
    Only provide defined characters.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.
    """
    two:  str = '0'  # use two character table.
    four: str = '1'  # use four character table.
    dash: str = '-'  # use four character count table.

    def __iter__(self):
        return iter(astuple(self))

CrySelDex = CrySelectCodex()  # Make instance


@dataclass(frozen=True)
class CryCntCodex:
    """
    CryCntCodex codex of four character length derivation codes that indicate
    count (number) of attached receipt couplets following a receipt statement .
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.
    .raw is empty

    Note binary length of everything in CryCntCodex results in 0 Base64 pad bytes.

    First two code characters select format of attached signatures
    Next two code charaters select count total of attached signatures to an event
    Only provide first two characters here
    """
    Base64: str =  '-A'  # Fully Qualified Base64 Format Receipt Couplets.
    Base2:  str =  '-B'  # Fully Qualified Base2 Format Receipt Couplets.

    def __iter__(self):
        return iter(astuple(self))

CryCntDex = CryCntCodex()  #  Make instance

# Mapping of Code to Size
# Total size  qb64
CryCntSizes = {
                "-A": 4,
                "-B": 4,
              }

# size of index portion of code qb64
CryCntIdxSizes = {
                   "-A": 2,
                   "-B": 2,
                 }

# total size of raw unqualified
CryCntRawSizes = {
                   "-A": 0,
                   "-B": 0,
                 }

CRYCNTMAX = 4095  # maximum count value given two base 64 digits


@dataclass(frozen=True)
class CryOneCodex:
    """
    CryOneCodex is codex of one character length derivation codes
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.

    Note binary length of everything in CryOneCodex results in 1 Base64 pad byte.
    """
    Ed25519_Seed:         str = 'A'  #  Ed25519 256 bit random seed for private key
    Ed25519N:             str = 'B'  #  Ed25519 verification key non-transferable, basic derivation.
    X25519:               str = 'C'  #  X25519 public encryption key, converted from Ed25519.
    Ed25519:              str = 'D'  #  Ed25519 verification key basic derivation
    Blake3_256:           str = 'E'  #  Blake3 256 bit digest self-addressing derivation.
    Blake2b_256:          str = 'F'  #  Blake2b 256 bit digest self-addressing derivation.
    Blake2s_256:          str = 'G'  #  Blake2s 256 bit digest self-addressing derivation.
    SHA3_256:             str = 'H'  #  SHA3 256 bit digest self-addressing derivation.
    SHA2_256:             str = 'I'  #  SHA2 256 bit digest self-addressing derivation.
    ECDSA_secp256k1_Seed: str = 'J'  #  ECDSA secp256k1 448 bit random Seed for private key
    Ed448_Seed:           str = 'K'  #  Ed448 448 bit random Seed for private key
    X448:                 str = 'L'  #  X448 public encryption key, converted from Ed448


    def __iter__(self):
        return iter(astuple(self))

CryOneDex = CryOneCodex()  # Make instance

# Mapping of Code to Size
CryOneSizes = {
               "A": 44, "B": 44, "C": 44, "D": 44, "E": 44, "F": 44,
               "G": 44, "H": 44, "I": 44, "J": 44, "K": 76, "L": 76,
              }

# Mapping of Code to Size
CryOneRawSizes = {
               "A": 32, "B": 32, "C": 32, "D": 32, "E": 32, "F": 32,
               "G": 32, "H": 32, "I": 32, "J": 32, "K": 56, "L": 56,
              }


@dataclass(frozen=True)
class CryTwoCodex:
    """
    CryTwoCodex is codex of two character length derivation codes
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.

    Note binary length of everything in CryTwoCodex results in 2 Base64 pad bytes.
    """
    Salt_128:    str = '0A'  # 128 bit random seed.
    Ed25519:     str = '0B'  # Ed25519 signature.
    ECDSA_256k1: str = '0C'  # ECDSA secp256k1 signature.


    def __iter__(self):
        return iter(astuple(self))

CryTwoDex = CryTwoCodex()  #  Make instance

# Mapping of Code to Size
CryTwoSizes = {
               "0A": 24,
               "0B": 88,
               "0B": 88,
              }

CryTwoRawSizes = {
                  "0A": 16,
                  "0B": 64,
                  "0B": 64,
                 }

@dataclass(frozen=True)
class CryFourCodex:
    """
    CryFourCodex codex of four character length derivation codes
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.

    Note binary length of everything in CryFourCodex results in 0 Base64 pad bytes.
    """
    ECDSA_256k1N:  str = "1AAA"  # ECDSA secp256k1 verification key non-transferable, basic derivation.
    ECDSA_256k1:   str = "1AAB"  # Ed25519 public verification or encryption key, basic derivation
    Ed448N:        str = "1AAC"  # Ed448 non-transferable prefix public signing verification key. Basic derivation.
    Ed448:         str = "1AAD"  # Ed448 public signing verification key. Basic derivation.
    Ed448_Sig:      str = "1AAE"  # Ed448 signature. Self-signing derivation.

    def __iter__(self):
        return iter(astuple(self))

CryFourDex = CryFourCodex()  #  Make instance

# Mapping of Code to Size
CryFourSizes = {
                "1AAA": 48,
                "1AAB": 48,
                "1AAC": 80,
                "1AAD": 80,
                "1AAE": 156,
               }

CryFourRawSizes = {
                   "1AAA": 33,
                   "1AAB": 33,
                   "1AAC": 57,
                   "1AAD": 57,
                   "1AAE": 114,
                  }

# all sizes in one dict
CrySizes = dict(CryCntSizes)
CrySizes.update(CryOneSizes)
CrySizes.update(CryTwoSizes)
CrySizes.update(CryFourSizes)

MINCRYSIZE = min(CrySizes.values())

# all sizes in one dict
CryRawSizes = dict(CryCntRawSizes)
CryRawSizes.update(CryOneRawSizes)
CryRawSizes.update(CryTwoRawSizes)
CryRawSizes.update(CryFourRawSizes)

# all sizes in one dict
CryIdxSizes = dict(CryCntIdxSizes)

@dataclass(frozen=True)
class CryNonTransCodex:
    """
    CryNonTransCodex is codex all non-transferable derivation codes
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.
    """
    Ed25519N:      str = 'B'  #  Ed25519 verification key non-transferable, basic derivation.
    ECDSA_256k1N:  str = "1AAA"  # ECDSA secp256k1 verification key non-transferable, basic derivation.
    Ed448N:        str = "1AAC"  # Ed448 non-transferable prefix public signing verification key. Basic derivation.

    def __iter__(self):
        return iter(astuple(self))

CryNonTransDex = CryNonTransCodex()  #  Make instance


@dataclass(frozen=True)
class CryDigCodex:
    """
    CryDigCodex is codex all digest derivation codes. This is needed to ensure
    delegated inception using a self-addressing derivation i.e. digest derivation
    code.
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.
    """
    Blake3_256:           str = 'E'  #  Blake3 256 bit digest self-addressing derivation.
    Blake2b_256:          str = 'F'  #  Blake2b 256 bit digest self-addressing derivation.
    Blake2s_256:          str = 'G'  #  Blake2s 256 bit digest self-addressing derivation.
    SHA3_256:             str = 'H'  #  SHA3 256 bit digest self-addressing derivation.
    SHA2_256:             str = 'I'  #  SHA2 256 bit digest self-addressing derivation.

    def __iter__(self):
        return iter(astuple(self))

CryDigDex = CryDigCodex()  #  Make instance

# secret derivation security tier
Tierage = namedtuple("Tierage", 'low med high')

Tiers = Tierage(low='low', med='med', high='high')


class CryMat:
    """
    CryMat is fully qualified cryptographic material base class
    Sub classes are derivation code and key event element context specific.

    Includes the following attributes and properties:

    Attributes:

    Properties:
        .pad  is int number of pad chars given raw
        .code is  str derivation code to indicate cypher suite
        .raw is bytes crypto material only without code
        .index is int count of attached crypto material by context (receipts)
        .qb64 is str in Base64 fully qualified with derivation code + crypto mat
        .qb64b is bytes in Base64 fully qualified with derivation code + crypto mat
        .qb2  is bytes in binary with derivation code + crypto material
        .nontrans is Boolean, True when non-transferable derivation code False otherwise

    Hidden:
        ._pad is method to compute  .pad property
        ._code is str value for .code property
        ._raw is bytes value for .raw property
        ._index is int value for .index property
        ._infil is method to compute fully qualified Base64 from .raw and .code
        ._exfil is method to extract .code and .raw from fully qualified Base64

    """

    def __init__(self, raw=None, qb64b=None, qb64=None, qb2=None,
                 code=CryOneDex.Ed25519N, index=0):
        """
        Validate as fully qualified
        Parameters:
            raw is bytes of unqualified crypto material usable for crypto operations
            qb64b is bytes of fully qualified crypto material
            qb64 is str or bytes  of fully qualified crypto material
            qb2 is bytes of fully qualified crypto material
            code is str of derivation code
            index is int of count of attached receipts for CryCntDex codes

        Needs (raw and code) or qb64b or qb64 or qb2 else raises EmptyMaterialError
        When raw and code provided then validate that code is correct for length of raw
            and assign .raw
        Else when qb64b or qb64 or qb2 provided extract and assign .raw and .code

        """
        if raw is not None:  #  raw provided
            if not code:
                raise EmptyMaterialError("Improper initialization need raw and code"
                                         " or qb64b or qb64 or qb2.")
            if not isinstance(raw, (bytes, bytearray)):
                raise TypeError("Not a bytes or bytearray, raw={}.".format(raw))
            pad = self._pad(raw)
            if (not ( (pad == 1 and (code in CryOneDex)) or  # One or Five or Nine
                      (pad == 2 and (code in CryTwoDex)) or  # Two or Six or Ten
                      (pad == 0 and (code in CryFourDex)) or # Four or Eight
                      (pad == 0 and (code in CryCntDex)) )):  # Cnt Four

                raise ValidationError("Wrong code={} for raw={}.".format(code, raw))

            if (code in CryCntDex and ((index < 0) or (index > CRYCNTMAX))):
                raise ValidationError("Invalid index={} for code={}.".format(index, code))

            raw = raw[:CryRawSizes[code]]  #  allows longer by truncating if stream
            if len(raw) != CryRawSizes[code]:  # forbids shorter
                raise ValidationError("Unexpected raw size={} for code={}"
                                      " not size={}.".format(len(raw),
                                                             code,
                                                             CryRawSizes[code]))

            self._code = code
            self._index = index
            self._raw = bytes(raw)  # crypto ops require bytes not bytearray

        elif qb64b is not None:
            self._exfil(qb64b)

        elif qb64 is not None:
            if hasattr(qb64, "encode"):  #  ._exfil expects bytes not str
                qb64 = qb64.encode("utf-8")  #  greedy so do not use on stream
            self._exfil(qb64)

        elif qb2 is not None:  # rewrite to use direct binary exfiltration
            self._exfil(encodeB64(qb2))

        else:
            raise EmptyMaterialError("Improper initialization need raw and code"
                                     " or qb64b or qb64 or qb2.")


    @staticmethod
    def _pad(raw):
        """
        Returns number of pad characters that would result from converting raw
        to Base64 encoding
        raw is bytes or bytearray
        """
        m = len(raw) % 3
        return (3 - m if m else 0)


    @property
    def pad(self):
        """
        Returns number of pad characters that would result from converting
        self.raw to Base64 encoding
        self.raw is raw is bytes or bytearray
        """
        return self._pad(self._raw)


    @property
    def code(self):
        """
        Returns ._code
        Makes .code read only
        """
        return self._code


    @property
    def raw(self):
        """
        Returns ._raw
        Makes .raw read only
        """
        return self._raw


    @property
    def index(self):
        """
        Returns ._index
        Makes .index read only
        """
        return self._index


    def _infil(self):
        """
        Returns fully qualified base64 bytes given self.pad, self.code, self.count
        and self.raw
        code is Codex value
        count is attached receipt couple count when applicable for CryCntDex codes
        raw is bytes or bytearray
        """
        if self._code in CryCntDex:
            l = CryIdxSizes[self._code]  # count length b64 characters
            # full is pre code + index
            full = "{}{}".format(self._code, IntToB64(self._index, l=l))
        else:
            full = self._code

        pad = self.pad
        # valid pad for code length
        if len(full) % 4 != pad:  # pad is not remainder of len(code) % 4
            raise ValidationError("Invalid code = {} for converted raw pad = {}."
                                  .format(full, self.pad))
        # prepending derivation code and strip off trailing pad characters
        return (full.encode("utf-8") + encodeB64(self._raw)[:-pad])


    def _exfil(self, qb64b):
        """
        Extracts self.code and self.raw from qualified base64 bytes qb64b
        """
        if len(qb64b) < MINCRYSIZE:  # Need more bytes
            raise ShortageError("Need more bytes.")

        cs = 1  # code size  initially 1 to extract selector
        code = qb64b[:cs].decode("utf-8")  #  convert to str
        index = 0

        # need to map code to length so can only consume proper number of chars
        #  from front of qb64 so can use with full identifiers not just prefixes

        if code in CryOneDex:  # One Char code
            qb64b = qb64b[:CryOneSizes[code]]  # strip of full crymat

        elif code == CrySelDex.two: # first char of two char code
            cs += 1  # increase code size
            code = qb64b[0:cs].decode("utf-8")  #  get full code, convert to str
            if code not in CryTwoDex:
                raise ValidationError("Invalid derivation code = {} in {}.".format(code, qb64b))
            qb64b = qb64b[:CryTwoSizes[code]]  # strip of full crymat

        elif code == CrySelDex.four: # first char of four char cnt code
            cs += 3  # increase code size
            code = qb64b[0:cs].decode("utf-8")  #  get full code, convert to str
            if code not in CryFourDex:
                raise ValidationError("Invalid derivation code = {} in {}.".format(code, qb64b))
            qb64b = qb64b[:CryFourSizes[code]]  # strip of full crymat

        elif code == CrySelDex.dash:  #  '-' 2 char code + 2 char index count
            cs += 1  # increase code size
            code = qb64b[0:cs].decode("utf-8")  #  get full code, convert to str
            if code not in CryCntDex:  # 4 char = 2 code + 2 index
                raise ValidationError("Invalid derivation code = {} in {}.".format(code, qb64b))
            qb64b = qb64b[:CryCntSizes[code]]  # strip of full crymat
            cs += 2  # increase code size
            index = B64ToInt(qb64b[cs-2:cs].decode("utf-8"))  # last two characters for index

        else:
            raise ValueError("Improperly coded material = {}".format(qb64b))

        if len(qb64b) != CrySizes[code]:  # must be correct length
            if len(qb64b) <  CrySizes[code]:  #  need more bytes
                raise ShortageError("Need more bytes.")
            else:
                raise ValidationError("Bad qb64b size expected {}, got {} "
                                      "bytes.".format(CrySizes[code],
                                                      len(qb64b)))

        pad = cs % 4  # pad is remainder pre mod 4
        # strip off prepended code and append pad characters
        base = qb64b[cs:] + pad * BASE64_PAD
        raw = decodeB64(base)

        if len(raw) != (len(qb64b) - cs) * 3 // 4:  # exact lengths
            raise ValueError("Improperly qualified material = {}".format(qb64b))

        self._code = code
        self._index = index
        self._raw = raw


    @property
    def qb64b(self):
        """
        Property qb64b:
        Returns Fully Qualified Base64 Version encoded as bytes
        Assumes self.raw and self.code are correctly populated
        """
        return self._infil()


    @property
    def qb64(self):
        """
        Property qb64:
        Returns Fully Qualified Base64 Version
        Assumes self.raw and self.code are correctly populated
        """
        return self.qb64b.decode("utf-8")


    @property
    def qb2(self):
        """
        Property qb2:
        Returns Fully Qualified Binary Version Bytes
        redo to use b64 to binary decode table since faster
        """
        # rewrite to do direct binary infiltration by
        # decode self.code as bits and prepend to self.raw
        return decodeB64(self._infil())


    @property
    def transferable(self):
        """
        Property transferable:
        Returns True if identifier does not have non-transferable derivation code,
                False otherwise
        """
        return(self.code not in CryNonTransDex)


    @property
    def digestive(self):
        """
        Property digestable:
        Returns True if identifier has digest derivation code,
                False otherwise
        """
        return(self.code in CryDigDex)



class CryCounter(CryMat):
    """
    CryCounter is subclass of CryMat, cryptographic material,
    CryCrount provides count of following number of attached cryptographic
    material items in its .count property.
    Useful when parsing attached receipt couplets from stream where CryCounter
    instance qb64 is inserted after Serder of receipt statement and
    before attached receipt couplets.

    .raw is empty only the derivation code is part of qb64 etc.

    Changes default initialization code = CryCntDex.Base64
    Raises error on init if code not in CryCntDex

    See CryMat for inherited attributes and properties:

    Attributes:

    Properties:
        .count is int count of attached signatures (same as .index)

    Methods:


    """
    def __init__(self, raw=None, qb64b=None, qb64=None, qb2=None,
                 code=CryCntDex.Base64, index=None, count=None, **kwa):
        """

        Parameters:  See CryMat for inherted parameters
            count is int number of attached sigantures same as index

        """
        raw = b'' if raw is not None else raw  # force raw empty

        if raw is None and qb64b is None and qb64 is None and qb2 is None:
            raw = b''

        # accept either index or count to init index
        if count is not None:
            index = count
        if index is None:
            index = 1  # most common case

        super(CryCounter, self).__init__(raw=raw, qb64b=qb64b, qb64=qb64, qb2=qb2,
                                         code=code, index=index, **kwa)

        if self.code not in CryCntDex:
            raise ValidationError("Invalid code = {} for CryCounter."
                                  "".format(self.code))

    @property
    def count(self):
        """
        Property counter:
        Returns .index as count
        Assumes ._index is correctly assigned
        """
        return self.index


class Seqner(CryMat):
    """
    Seqner is subclass of CryMat, cryptographic material, for sequence numbers
    Seqner provides fully qualified format for sequence numbers when
    used as attached cryptographic material items.

    Useful when parsing attached receipt groupings with sn from stream or database

    Uses default initialization code = CryTwoDex.Salt_128
    Raises error on init if code not CryTwoDex.Salt_128

    Attributes:

    Inherited Properties:  (See CryMat)
        .pad  is int number of pad chars given raw
        .code is  str derivation code to indicate cypher suite
        .raw is bytes crypto material only without code
        .index is int count of attached crypto material by context (receipts)
        .qb64 is str in Base64 fully qualified with derivation code + crypto mat
        .qb64b is bytes in Base64 fully qualified with derivation code + crypto mat
        .qb2  is bytes in binary with derivation code + crypto material
        .nontrans is Boolean, True when non-transferable derivation code False otherwise

    Properties:
        .sn is int sequence number
        .snh is hex string representation of sequence number no leading zeros

    Hidden:
        ._pad is method to compute  .pad property
        ._code is str value for .code property
        ._raw is bytes value for .raw property
        ._index is int value for .index property
        ._infil is method to compute fully qualified Base64 from .raw and .code
        ._exfil is method to extract .code and .raw from fully qualified Base64


    Methods:


    """
    def __init__(self, raw=None, qb64b=None, qb64=None, qb2=None,
                 code=CryTwoDex.Salt_128, sn=None, snh=None, **kwa):
        """
        Inhereited Parameters:  (see CryMat)
            raw is bytes of unqualified crypto material usable for crypto operations
            qb64b is bytes of fully qualified crypto material
            qb64 is str or bytes  of fully qualified crypto material
            qb2 is bytes of fully qualified crypto material
            code is str of derivation code
            index is int of count of attached receipts for CryCntDex codes


        Parameters:
            sn is int sequence number
            snh is hex string of sequence number

        """
        if sn is None:
            if snh is None:
                sn = 0
            else:
                sn = int(snh, 16)

        if raw is None and qb64b is None and qb64 is None and qb2 is None:
            raw = sn.to_bytes(CryRawSizes[CryTwoDex.Salt_128], 'big')

        super(Seqner, self).__init__(raw=raw, qb64b=qb64b, qb64=qb64, qb2=qb2,
                                         code=code, **kwa)

        if self.code != CryTwoDex.Salt_128:
            raise ValidationError("Invalid code = {} for SeqNumber."
                                  "".format(self.code))

    @property
    def sn(self):
        """
        Property sn:
        Returns .raw converted to int
        """
        return int.from_bytes(self.raw, 'big')

    @property
    def snh(self):
        """
        Property snh:
        Returns .raw converted to hex str
        """
        return "{:x}".format(self.sn)


class Verfer(CryMat):
    """
    Verfer is CryMat subclass with method to verify signature of serialization
    using the .raw as verifier key and .code for signature cipher suite.

    See CryMat for inherited attributes and properties:

    Attributes:

    Properties:

    Methods:
        verify: verifies signature

    """
    def __init__(self, **kwa):
        """
        Assign verification cipher suite function to ._verify

        """
        super(Verfer, self).__init__(**kwa)

        if self.code in [CryOneDex.Ed25519N, CryOneDex.Ed25519]:
            self._verify = self._ed25519
        else:
            raise ValueError("Unsupported code = {} for verifier.".format(self.code))


    def verify(self, sig, ser):
        """
        Returns True if bytes signature sig verifies on bytes serialization ser
        using .raw as verifier public key for ._verify cipher suite determined
        by .code

        Parameters:
            sig is bytes signature
            ser is bytes serialization
        """
        return (self._verify(sig=sig, ser=ser, key=self.raw))

    @staticmethod
    def _ed25519(sig, ser, key):
        """
        Returns True if verified False otherwise
        Verifiy ed25519 sig on ser using key

        Parameters:
            sig is bytes signature
            ser is bytes serialization
            key is bytes public key
        """
        try:  # verify returns None if valid else raises ValueError
            pysodium.crypto_sign_verify_detached(sig, ser, key)
        except Exception as ex:
            return False

        return True


class Cigar(CryMat):
    """
    Cigar is CryMat subclass holding a nonindexed signature with verfer property.
        From CryMat .raw is signature and .code is signature cipher suite
    Adds .verfer property to hold Verfer instance of associated verifier public key
        Verfer's .raw as verifier key and .code is verifier cipher suite.

    See CryMat for inherited attributes and properties:

    Attributes:

    Inherited Properties:
        .pad  is int number of pad chars given raw
        .code is  str derivation code to indicate cypher suite
        .raw is bytes crypto material only without code
        .index is int count of attached crypto material by context (receipts)
        .qb64 is str in Base64 fully qualified with derivation code + crypto mat
        .qb64b is bytes in Base64 fully qualified with derivation code + crypto mat
        .qb2  is bytes in binary with derivation code + crypto material
        .nontrans is Boolean, True when non-transferable derivation code False otherwise

    Properties:
        .verfer is verfer of public key used to verify signature


    Methods:

    Hidden:
        ._pad is method to compute  .pad property
        ._code is str value for .code property
        ._raw is bytes value for .raw property
        ._index is int value for .index property
        ._infil is method to compute fully qualified Base64 from .raw and .code
        ._exfil is method to extract .code and .raw from fully qualified Base64

    """
    def __init__(self, verfer=None, **kwa):
        """
        Assign verfer to ._verfer attribute

        """
        super(Cigar, self).__init__(**kwa)

        self._verfer = verfer


    @property
    def verfer(self):
        """
        Property verfer:
        Returns Verfer instance
        Assumes ._verfer is correctly assigned
        """
        return self._verfer

    @verfer.setter
    def verfer(self, verfer):
        """ verfer property setter """
        self._verfer = verfer


class Signer(CryMat):
    """
    Signer is CryMat subclass with method to create signature of serialization
    using the .raw as signing (private) key seed, .code as cipher suite for
    signing and new property .verfer whose property .raw is public key for signing.
    If not provided .verfer is generated from private key seed using .code
    as cipher suite for creating key-pair.


    See CryMat for inherited attributes and properties:

    Attributes:

    Properties:
        .verfer is Verfer object instance

    Methods:
        sign: create signature

    """
    def __init__(self,raw=None, code=CryOneDex.Ed25519_Seed, transferable=True, **kwa):
        """
        Assign signing cipher suite function to ._sign

        Parameters:  See CryMat for inherted parameters
            raw is bytes crypto material seed or private key
            code is derivation code
            transferable is Boolean True means verifier code is transferable
                                    False othersize non-transerable

        """
        try:
            super(Signer, self).__init__(raw=raw, code=code, **kwa)
        except EmptyMaterialError as ex:
            if code == CryOneDex.Ed25519_Seed:
                raw = pysodium.randombytes(pysodium.crypto_sign_SEEDBYTES)
                super(Signer, self).__init__(raw=raw, code=code, **kwa)
            else:
                raise ValueError("Unsupported signer code = {}.".format(code))

        if self.code == CryOneDex.Ed25519_Seed:
            self._sign = self._ed25519
            verkey, sigkey = pysodium.crypto_sign_seed_keypair(self.raw)
            verfer = Verfer(raw=verkey,
                                code=CryOneDex.Ed25519 if transferable
                                                    else CryOneDex.Ed25519N )
        else:
            raise ValueError("Unsupported signer code = {}.".format(self.code))

        self._verfer = verfer

    @property
    def verfer(self):
        """
        Property verfer:
        Returns Verfer instance
        Assumes ._verfer is correctly assigned
        """
        return self._verfer

    def sign(self, ser, index=None):
        """
        Returns either Cigar or Siger (indexed) instance of cryptographic
        signature material on bytes serialization ser

        If index is None
            return Cigar instance
        Else
            return Siger instance

        Parameters:
            ser is bytes serialization
            index is int index of associated verifier key in event keys
        """
        return (self._sign(ser=ser,
                           seed=self.raw,
                           verfer=self.verfer,
                           index=index))

    @staticmethod
    def _ed25519(ser, seed, verfer, index):
        """
        Returns signature


        Parameters:
            ser is bytes serialization
            seed is bytes seed (private key)
            verfer is Verfer instance. verfer.raw is public key
            index is index of offset into signers list or None

        """
        sig = pysodium.crypto_sign_detached(ser, seed + verfer.raw)
        if index is None:
            return Cigar(raw=sig, code=CryTwoDex.Ed25519, verfer=verfer)
        else:
            return Siger(raw=sig,
                          code=SigTwoDex.Ed25519,
                          index=index,
                          verfer=verfer)


class Salter(CryMat):
    """
    Salter is CryMat subclass to maintain random salt for secrets (private keys)
    Its .raw is random salt, .code as cipher suite for salt

    Attributes:
        .level is str security level code. Provides default level

    Inherited Properties
        .pad  is int number of pad chars given raw
        .code is  str derivation code to indicate cypher suite
        .raw is bytes crypto material only without code
        .index is int count of attached crypto material by context (receipts)
        .qb64 is str in Base64 fully qualified with derivation code + crypto mat
        .qb64b is bytes in Base64 fully qualified with derivation code + crypto mat
        .qb2  is bytes in binary with derivation code + crypto material
        .nontrans is Boolean, True when non-transferable derivation code False otherwise

    Properties:

    Methods:

    Hidden:
        ._pad is method to compute  .pad property
        ._code is str value for .code property
        ._raw is bytes value for .raw property
        ._index is int value for .index property
        ._infil is method to compute fully qualified Base64 from .raw and .code
        ._exfil is method to extract .code and .raw from fully qualified Base64

    """
    Tier = Tiers.low

    def __init__(self,raw=None, code=CryTwoDex.Salt_128, tier=None, **kwa):
        """
        Initialize salter's raw and code

        Inherited Parameters:
            raw is bytes of unqualified crypto material usable for crypto operations
            qb64b is bytes of fully qualified crypto material
            qb64 is str or bytes  of fully qualified crypto material
            qb2 is bytes of fully qualified crypto material
            code is str of derivation code
            index is int of count of attached receipts for CryCntDex codes

        Parameters:

        """
        try:
            super(Salter, self).__init__(raw=raw, code=code, **kwa)
        except EmptyMaterialError as ex:
            if code == CryTwoDex.Salt_128:
                raw = pysodium.randombytes(pysodium.crypto_pwhash_SALTBYTES)
                super(Salter, self).__init__(raw=raw, code=code, **kwa)
            else:
                raise ValueError("Unsupported salter code = {}.".format(code))

        if self.code not in (CryTwoDex.Salt_128, ):
            raise ValueError("Unsupported salter code = {}.".format(self.code))

        self.tier = tier if tier is not None else self.Tier


    def signer(self, path="", tier=None, code=CryOneDex.Ed25519_Seed,
               transferable=True, temp=False):
        """
        Returns Signer instance whose .raw secret is derived from path and
        salter's .raw and streched to size given by code. The signers public key
        for its .verfer is derived from code and transferable.

        Parameters:
            path is str of unique chars used in derivation of secret seed for signer
            code is str code of secret crypto suite
            transferable is Boolean, True means use transferace code for public key
            temp is Boolean, True means use quick method to stretch salt
                    for testing only, Otherwise use more time to stretch
        """
        tier = tier if tier is not None else self.tier

        if temp:
            opslimit = pysodium.crypto_pwhash_OPSLIMIT_MIN
            memlimit = pysodium.crypto_pwhash_MEMLIMIT_MIN
        else:
            if tier == Tiers.low:
                opslimit = pysodium.crypto_pwhash_OPSLIMIT_INTERACTIVE
                memlimit = pysodium.crypto_pwhash_MEMLIMIT_INTERACTIVE
            elif tier == Tiers.med:
                opslimit = pysodium.crypto_pwhash_OPSLIMIT_MODERATE
                memlimit = pysodium.crypto_pwhash_MEMLIMIT_MODERATE
            elif tier == Tiers.high:
                opslimit = pysodium.crypto_pwhash_OPSLIMIT_SENSITIVE
                memlimit = pysodium.crypto_pwhash_MEMLIMIT_SENSITIVE
            else:
                raise ValueError("Unsupported security tier = {}.".format(tier))

         # stretch algorithm is argon2id
        seed = pysodium.crypto_pwhash(outlen=CryRawSizes[code],
                                      passwd=path,
                                      salt=self.raw,
                                      opslimit=opslimit,
                                      memlimit=memlimit,
                                      alg=pysodium.crypto_pwhash_ALG_DEFAULT)

        return (Signer(raw=seed, code=code, transferable=transferable))


def generateSigners(salt=None, count=8, transferable=True):
    """
    Returns list of Signers for Ed25519

    Parameters:
        salt is bytes 16 byte long root cryptomatter from which seeds for Signers
            in list are derived
            random salt created if not provided
        count is number of signers in list
        transferable is boolean true means signer.verfer code is transferable
                                non-transferable otherwise
    """
    if not salt:
        salt = pysodium.randombytes(pysodium.crypto_pwhash_SALTBYTES)

    signers = []
    for i in range(count):
        path = "{:x}".format(i)
        # algorithm default is argon2id
        seed = pysodium.crypto_pwhash(outlen=32,
                                      passwd=path,
                                      salt=salt,
                                      opslimit=pysodium.crypto_pwhash_OPSLIMIT_INTERACTIVE,
                                      memlimit=pysodium.crypto_pwhash_MEMLIMIT_INTERACTIVE,
                                      alg=pysodium.crypto_pwhash_ALG_DEFAULT)

        signers.append(Signer(raw=seed, transferable=transferable))

    return signers


def generateSecrets(salt=None, count=8):
    """
    Returns list of fully qualified Base64 secret seeds for Ed25519 private keys

    Parameters:
        salt is bytes 16 byte long root cryptomatter from which seeds for Signers
            in list are derived
            random salt created if not provided
        count is number of signers in list
    """
    signers = generateSigners(salt=salt, count=count)

    return [signer.qb64 for signer in signers]  #  fetch the qb64 as secret


class Diger(CryMat):
    """
    Diger is CryMat subclass with method to verify digest of serialization
    using  .raw as digest and .code for digest algorithm.

    See CryMat for inherited attributes and properties:

    Inherited Properties:
        .pad  is int number of pad chars given raw
        .code is  str derivation code to indicate cypher suite
        .raw is bytes crypto material only without code
        .index is int count of attached crypto material by context (receipts)
        .qb64 is str in Base64 fully qualified with derivation code + crypto mat
        .qb64b is bytes in Base64 fully qualified with derivation code + crypto mat
        .qb2  is bytes in binary with derivation code + crypto material
        .nontrans is Boolean, True when non-transferable derivation code False otherwise

    Methods:
        verify: verifies digest given ser
        compare: compares provide digest given ser to this digest of ser.
                enables digest agility of different digest algos to compare.

    Hidden:
        ._pad is method to compute  .pad property
        ._code is str value for .code property
        ._raw is bytes value for .raw property
        ._index is int value for .index property
        ._infil is method to compute fully qualified Base64 from .raw and .code
        ._exfil is method to extract .code and .raw from fully qualified Base64

    """
    def __init__(self, raw=None, ser=None, code=CryOneDex.Blake3_256, **kwa):
        """
        Assign digest verification function to ._verify

        See CryMat for inherited parameters

        Inherited Parameters:
            raw is bytes of unqualified crypto material usable for crypto operations
            qb64b is bytes of fully qualified crypto material
            qb64 is str or bytes  of fully qualified crypto material
            qb2 is bytes of fully qualified crypto material
            code is str of derivation code
            index is int of count of attached receipts for CryCntDex codes

        Parameters:
           ser is bytes serialization from which raw is computed if not raw

        """
        try:
            super(Diger, self).__init__(raw=raw, code=code, **kwa)
        except EmptyMaterialError as ex:
            if not ser:
                raise ex
            if code == CryOneDex.Blake3_256:
                dig = blake3.blake3(ser).digest()
            elif code == CryOneDex.Blake2b_256:
                dig = hashlib.blake2b(ser, digest_size=32).digest()
            elif code == CryOneDex.Blake2s_256:
                dig = hashlib.blake2s(ser, digest_size=32).digest()
            elif code == CryOneDex.SHA3_256:
                dig = hashlib.sha3_256(ser).digest()
            elif code == CryOneDex.SHA2_256:
                dig = hashlib.sha256(ser).digest()
            else:
                raise ValueError("Unsupported code = {} for digester.".format(code))

            super(Diger, self).__init__(raw=dig, code=code, **kwa)

        if self.code == CryOneDex.Blake3_256:
            self._verify = self._blake3_256
        elif self.code == CryOneDex.Blake2b_256:
            self._verify = self._blake2b_256
        elif self.code == CryOneDex.Blake2s_256:
            self._verify = self._blake2s_256
        elif self.code == CryOneDex.SHA3_256:
            self._verify = self._sha3_256
        elif self.code == CryOneDex.SHA2_256:
            self._verify = self._sha2_256
        else:
            raise ValueError("Unsupported code = {} for digester.".format(self.code))


    def verify(self, ser):
        """
        Returns True if digest of bytes serialization ser matches .raw
        using .raw as reference digest for ._verify digest algorithm determined
        by .code

        Parameters:
            ser is bytes serialization
        """
        return (self._verify(ser=ser, raw=self.raw))


    def compare(self, ser, dig=None, diger=None):
        """
        Returns True  if dig and .qb64 or .qb64b match or
            if both .raw and dig are valid digests of ser
            Otherwise returns False

        Parameters:
            ser is bytes serialization
            dig is qb64b or qb64 digest of ser to compare with self
            diger is Diger instance of digest of ser to compare with self

            if both supplied dig takes precedence


        If both match then as optimization returns True and does not verify either
          as digest of ser
        If both have same code but do not match then as optimization returns False
           and does not verify if either is digest of ser
        But if both do not match then recalcs both digests to verify they
        they are both digests of ser with or without matching codes.
        """
        if dig is not None:
            if hasattr(dig, "encode"):
                dig = dig.encode('utf-8')  #  makes bytes

            if dig == self.qb64b:  #  matching
                return True

            diger = Diger(qb64b=dig)  # extract code

        elif diger is not None:
            if diger.qb64b == self.qb64b:
                return True

        else:
            raise ValueError("Both dig and diger may not be None.")

        if diger.code == self.code: # digest not match but same code
            return False

        if diger.verify(ser=ser) and self.verify(ser=ser):  # both verify on ser
            return True

        return (False)


    @staticmethod
    def _blake3_256(ser, raw):
        """
        Returns True if verified False otherwise
        Verifiy blake3_256 digest of ser matches raw

        Parameters:
            ser is bytes serialization
            dig is bytes reference digest
        """
        return(blake3.blake3(ser).digest() == raw)

    @staticmethod
    def _blake2b_256(ser, raw):
        """
        Returns True if verified False otherwise
        Verifiy blake2b_256 digest of ser matches raw

        Parameters:
            ser is bytes serialization
            dig is bytes reference digest
        """
        return(hashlib.blake2b(ser, digest_size=32).digest() == raw)

    @staticmethod
    def _blake2s_256(ser, raw):
        """
        Returns True if verified False otherwise
        Verifiy blake2s_256 digest of ser matches raw

        Parameters:
            ser is bytes serialization
            dig is bytes reference digest
        """
        return(hashlib.blake2s(ser, digest_size=32).digest() == raw)

    @staticmethod
    def _sha3_256(ser, raw):
        """
        Returns True if verified False otherwise
        Verifiy blake2s_256 digest of ser matches raw

        Parameters:
            ser is bytes serialization
            dig is bytes reference digest
        """
        return(hashlib.sha3_256(ser).digest() == raw)

    @staticmethod
    def _sha2_256(ser, raw):
        """
        Returns True if verified False otherwise
        Verifiy blake2s_256 digest of ser matches raw

        Parameters:
            ser is bytes serialization
            dig is bytes reference digest
        """
        return(hashlib.sha256(ser).digest() == raw)



class Nexter(CryMat):
    """
    Nexter is CryMat subclass with support to derive itself from
    next sith and next keys given code.

    See Diger for inherited attributes and properties:

    Attributes:

    Inherited Properties:
        .code  str derivation code to indicate cypher suite
        .raw   bytes crypto material only without code
        .pad  int number of pad chars given raw
        .qb64 str in Base64 fully qualified with derivation code + crypto mat
        .qb64b bytes in Base64 fully qualified with derivation code + crypto mat
        .qb2  bytes in binary with derivation code + crypto material
        .nontrans True when non-transferable derivation code False otherwise

    Properties:

    Methods:

    Hidden:
        ._digest is digest method
        ._derive is derivation method


    """
    def __init__(self, limen=None, sith=None, digs=None, keys=None, ked=None,
                 code=CryOneDex.Blake3_256, **kwa):
        """
        Assign digest verification function to ._verify

        Inherited Parameters:
            raw is bytes of unqualified crypto material usable for crypto operations
            qb64b is bytes of fully qualified crypto material
            qb64 is str or bytes  of fully qualified crypto material
            qb2 is bytes of fully qualified crypto material
            code is str of derivation code
            index is int of count of attached receipts for CryCntDex codes

        Parameters:
           limen is string extracted from sith expression in event
           sith is int threshold or lowercase hex str no leading zeros
           digs is list of qb64 digests of public keys
           keys is list of keys each is qb64 public key str
           ked is key event dict

           Raises error if not any of raw, digs,keys, ked

           if not raw
               use digs
               If digs not provided
                  use keys
                  if keys not provided
                     get keys from ked
                  compute digs from keys

           If sith not provided
               get sith from ked
               but if not ked then compute sith as simple majority of keys

        """
        try:
            super(Nexter, self).__init__(code=code, **kwa)
        except EmptyMaterialError as ex:
            if not digs and not keys and not ked:
                raise ex
            if code == CryOneDex.Blake3_256:
                self._digest = self._blake3_256
            else:
                raise ValueError("Unsupported code = {} for nexter.".format(code))

            raw = self._derive(code=code, limen=limen, sith=sith, digs=digs,
                               keys=keys, ked=ked)  #  derive nxt raw
            super(Nexter, self).__init__(raw=raw, code=code, **kwa)  # attaches code etc

        else:
            if self.code == CryOneDex.Blake3_256:
                self._digest = self._blake3_256
            else:
                raise ValueError("Unsupported code = {} for nexter.".format(code))


    def verify(self, raw=b'', limen=None, sith=None, digs=None, keys=None, ked=None):
        """
        Returns True if digest of bytes nxt raw matches .raw
        Uses .raw as reference nxt raw for ._verify algorithm determined by .code

        If raw not provided then extract raw from either (sith, keys) or ked

        Parameters:
            raw is bytes serialization
            sith is str lowercase hex
            keys is list of keys qb64
            ked is key event dict
        """
        if not raw:
            raw = self._derive(code=self.code, limen=limen, sith=sith, digs=digs,
                               keys=keys, ked=ked)

        return (raw == self.raw)


    def _derive(self, code, limen=None, sith=None, digs=None, keys=None, ked=None):
        """
        Returns ser where ser is serialization derived from code, sith, keys, or ked
        """
        if not digs:
            if not keys:
                try:
                    keys = ked["k"]
                except KeyError as ex:
                    raise DerivationError("Error extracting keys from"
                                          " ked = {}".format(ex))

            if not keys:  # empty keys
                raise DerivationError("Empty keys.")

            keydigs = [self._digest(key.encode("utf-8")) for key in keys]

        else:
            digers = [Diger(qb64=dig) for dig in digs]
            for diger in digers:
                if diger.code != code:
                    raise DerivationError("Mismatch of public key digest "
                                          "code = {} for next digest code = {}."
                                          "".format(diger.code, code))
            keydigs = [diger.raw for diger in digers]

        if limen is None:  # compute default limen
            if sith is None:  # need len keydigs to compute default sith
                try:
                    sith = ked["kt"]
                except Exception as ex:
                    # default simple majority
                    sith = "{:x}".format(max(1, ceil(len(keydigs) / 2)))

            limen = Tholder(sith=sith).limen

        kints = [int.from_bytes(keydig, 'big') for keydig in keydigs]
        sint = int.from_bytes(self._digest(limen.encode("utf-8")), 'big')
        for kint in kints:
            sint ^= kint  # xor together

        return (sint.to_bytes(CryRawSizes[code], 'big'))


    @staticmethod
    def _blake3_256(raw):
        """
        Returns digest of raw using Blake3_256

        Parameters:
            raw is bytes serialization of nxt raw
        """
        return(blake3.blake3(raw).digest())



class Prefixer(CryMat):
    """
    Prefixer is CryMat subclass for autonomic identifier prefix using
    derivation as determined by code from ked

    Attributes:

    Inherited Properties:  (see CryMat)
        .pad  is int number of pad chars given raw
        .code is  str derivation code to indicate cypher suite
        .raw is bytes crypto material only without code
        .index is int count of attached crypto material by context (receipts)
        .qb64 is str in Base64 fully qualified with derivation code + crypto mat
        .qb64b is bytes in Base64 fully qualified with derivation code + crypto mat
        .qb2  is bytes in binary with derivation code + crypto material
        .nontrans is Boolean, True when non-transferable derivation code False otherwise

    Properties:

    Methods:
        verify():  Verifies derivation of aid prefix from a ked

    Hidden:
        ._pad is method to compute  .pad property
        ._code is str value for .code property
        ._raw is bytes value for .raw property
        ._index is int value for .index property
        ._infil is method to compute fully qualified Base64 from .raw and .code
        ._exfil is method to extract .code and .raw from fully qualified Base64
    """
    Dummy = "#"  # dummy spaceholder char for pre. Must not be a valid Base64 char
    # element labels to exclude in digest or signature derivation from inception icp
    IcpExcludes = ["i"]
    # element labels to exclude in digest or signature derivation from delegated inception dip
    DipExcludes = ["i"]

    def __init__(self, raw=None, code=None, ked=None,
                 seed=None, secret=None, **kwa):
        """
        assign ._derive to derive derivatin of aid prefix from ked
        assign ._verify to verify derivation of aid prefix  from ked

        Default code is None to force EmptyMaterialError when only raw provided but
        not code.

        Inherited Parameters:
            raw is bytes of unqualified crypto material usable for crypto operations
            qb64b is bytes of fully qualified crypto material
            qb64 is str or bytes  of fully qualified crypto material
            qb2 is bytes of fully qualified crypto material
            code is str of derivation code
            index is int of count of attached receipts for CryCntDex codes

        Parameters:
            seed is bytes seed when signature derivation
            secret is qb64 when signature derivation when applicable
               one of seed or secret must be provided when signature derivation

        """
        try:
            super(Prefixer, self).__init__(raw=raw, code=code, **kwa)
        except EmptyMaterialError as ex:
            if not  ked or (not code and "i" not in ked):
                raise  ex

            if not code:  # get code from pre in ked
                super(Prefixer, self).__init__(qb64=ked["i"], code=code, **kwa)
                code = self.code

            if code == CryOneDex.Ed25519N:
                self._derive = self._derive_ed25519N
            elif code == CryOneDex.Ed25519:
                self._derive = self._derive_ed25519
            elif code == CryOneDex.Blake3_256:
                self._derive = self._derive_blake3_256
            elif code == CryTwoDex.Ed25519:
                self._derive = self._derive_sig_ed25519
            else:
                raise ValueError("Unsupported code = {} for prefixer.".format(code))

            # use ked and ._derive from code to derive aid prefix and code
            raw, code = self._derive(ked=ked, seed=seed, secret=secret)
            super(Prefixer, self).__init__(raw=raw, code=code, **kwa)

        if self.code == CryOneDex.Ed25519N:
            self._verify = self._verify_ed25519N
        elif self.code == CryOneDex.Ed25519:
            self._verify = self._verify_ed25519
        elif self.code == CryOneDex.Blake3_256:
            self._verify = self._verify_blake3_256
        elif code == CryTwoDex.Ed25519:
            self._verify = self._verify_sig_ed25519
        else:
            raise ValueError("Unsupported code = {} for prefixer.".format(self.code))


    def derive(self, ked, seed=None, secret=None):
        """
        Returns tuple (raw, code) of aid prefix as derived from key event dict ked.
                uses a derivation code specific _derive method

        Parameters:
            ked is inception key event dict
            seed is only used for sig derivation it is the secret key/secret

        """
        if ked["t"] not in (Ilks.icp, Ilks.dip):
            raise ValueError("Nonincepting ilk={} for prefix derivation.".format(ked["t"]))
        return (self._derive(ked=ked, seed=seed, secret=secret))


    def verify(self, ked, prefixed=False):
        """
        Returns True if derivation from ked for .code matches .qb64 and
                If prefixed also verifies ked["i"] matches .qb64
                False otherwise

        Parameters:
            ked is inception key event dict
        """
        if ked["t"] not in (Ilks.icp, Ilks.dip):
            raise ValueError("Nonincepting ilk={} for prefix derivation.".format(ked["t"]))
        return (self._verify(ked=ked, pre=self.qb64, prefixed=prefixed))


    def _derive_ed25519N(self, ked, seed=None, secret=None):
        """
        Returns tuple (raw, code) of basic nontransferable Ed25519 prefix (qb64)
            as derived from inception key event dict ked keys[0]
        """
        ked = dict(ked)  # make copy so don't clobber original ked
        try:
            keys = ked["k"]
            if len(keys) != 1:
                raise DerivationError("Basic derivation needs at most 1 key "
                                      " got {} keys instead".format(len(keys)))
            verfer = Verfer(qb64=keys[0])
        except Exception as ex:
            raise DerivationError("Error extracting public key ="
                                  " = {}".format(ex))

        if verfer.code not in [CryOneDex.Ed25519N]:
            raise DerivationError("Mismatch derivation code = {}."
                                  "".format(verfer.code))

        try:
            if verfer.code == CryOneDex.Ed25519N and ked["n"]:
                raise DerivationError("Non-empty nxt = {} for non-transferable"
                                      " code = {}".format(ked["n"],
                                                          verfer.code))
        except Exception as ex:
            raise DerivationError("Error checking nxt = {}".format(ex))

        return (verfer.raw, verfer.code)


    def _verify_ed25519N(self, ked, pre, prefixed=False):
        """
        Returns True if verified  False otherwise
        Verify derivation of fully qualified Base64 pre from inception iked dict

        Parameters:
            ked is inception key event dict
            pre is Base64 fully qualified prefix default to .qb64
        """
        try:
            keys = ked["k"]
            if len(keys) != 1:
                return False

            if keys[0] != pre:
                return False

            if prefixed and ked["i"] != pre:
                return False

            if ked["n"]:  # must be empty
                return False

        except Exception as ex:
            return False

        return True


    def _derive_ed25519(self, ked, seed=None, secret=None):
        """
        Returns tuple (raw, code) of basic Ed25519 prefix (qb64)
            as derived from inception key event dict ked keys[0]
        """
        ked = dict(ked)  # make copy so don't clobber original ked
        try:
            keys = ked["k"]
            if len(keys) != 1:
                raise DerivationError("Basic derivation needs at most 1 key "
                                      " got {} keys instead".format(len(keys)))
            verfer = Verfer(qb64=keys[0])
        except Exception as ex:
            raise DerivationError("Error extracting public key ="
                                  " = {}".format(ex))

        if verfer.code not in [CryOneDex.Ed25519]:
            raise DerivationError("Mismatch derivation code = {}"
                                  "".format(verfer.code))

        return (verfer.raw, verfer.code)


    def _verify_ed25519(self, ked, pre, prefixed=False):
        """
        Returns True if verified False otherwise
        Verify derivation of fully qualified Base64 prefix from
        inception key event dict (ked)

        Parameters:
            ked is inception key event dict
            pre is Base64 fully qualified prefix default to .qb64
        """
        try:
            keys = ked["k"]
            if len(keys) != 1:
                return False

            if keys[0] != pre:
                return False

            if prefixed and ked["i"] != pre:
                return False

        except Exception as ex:
            return False

        return True


    def _derive_blake3_256(self, ked, seed=None, secret=None):
        """
        Returns tuple (raw, code) of basic Ed25519 pre (qb64)
            as derived from inception key event dict ked
        """
        ked = dict(ked)  # make copy so don't clobber original ked
        ilk = ked["t"]
        if ilk == Ilks.icp:
            labels = [key for key in ked if key not in self.IcpExcludes]
        elif ilk == Ilks.dip:
            labels = [key for key in ked if key not in self.DipExcludes]
        else:
            raise DerivationError("Invalid ilk = {} to derive pre.".format(ilk))

        # put in dummy pre to get size correct
        ked["i"] = "{}".format(self.Dummy*CryOneSizes[CryOneDex.Blake3_256])
        serder = Serder(ked=ked)
        ked = serder.ked  # use updated ked with valid vs element

        for l in labels:
            if l not in ked:
                raise DerivationError("Missing element = {} from ked.".format(l))

        dig =  blake3.blake3(serder.raw).digest()
        return (dig, CryOneDex.Blake3_256)


    def _verify_blake3_256(self, ked, pre, prefixed=False):
        """
        Returns True if verified False otherwise
        Verify derivation of fully qualified Base64 prefix from
        inception key event dict (ked)

        Parameters:
            ked is inception key event dict
            pre is Base64 fully qualified default to .qb64
        """
        try:
            raw, code =  self._derive_blake3_256(ked=ked)
            crymat = CryMat(raw=raw, code=CryOneDex.Blake3_256)
            if crymat.qb64 != pre:
                return False

            if prefixed and ked["i"] != pre:
                return False

        except Exception as ex:
            return False

        return True


    def _derive_sig_ed25519(self, ked, seed=None, secret=None):
        """
        Returns tuple (raw, code) of basic Ed25519 pre (qb64)
            as derived from inception key event dict ked
        """
        ked = dict(ked)  # make copy so don't clobber original ked
        ilk = ked["t"]
        if ilk == Ilks.icp:
            labels = [key for key in ked if key not in self.IcpExcludes]
        elif ilk == Ilks.dip:
            labels = [key for key in ked if key not in self.DipExcludes]
        else:
            raise DerivationError("Invalid ilk = {} to derive pre.".format(ilk))

        # put in dummy pre to get size correct
        ked["i"] = "{}".format(self.Dummy*CryTwoSizes[CryTwoDex.Ed25519])
        serder = Serder(ked=ked)
        ked = serder.ked  # use updated ked with valid vs element

        for l in labels:
            if l not in ked:
                raise DerivationError("Missing element = {} from ked.".format(l))

        try:
            keys = ked["k"]
            if len(keys) != 1:
                raise DerivationError("Basic derivation needs at most 1 key "
                                      " got {} keys instead".format(len(keys)))
            verfer = Verfer(qb64=keys[0])
        except Exception as ex:
            raise DerivationError("Error extracting public key ="
                                  " = {}".format(ex))

        if verfer.code not in [CryOneDex.Ed25519]:
            raise DerivationError("Invalid derivation code = {}"
                                  "".format(verfer.code))

        if not (seed or secret):
            raise DerivationError("Missing seed or secret.")

        signer = Signer(raw=seed, qb64=secret)

        if verfer.raw != signer.verfer.raw:
            raise DerivationError("Key in ked not match seed.")

        cigar = signer.sign(ser=serder.raw)

        # sig = pysodium.crypto_sign_detached(ser, signer.raw + verfer.raw)

        return (cigar.raw, CryTwoDex.Ed25519)


    def _verify_sig_ed25519(self, ked, pre, prefixed=False):
        """
        Returns True if verified False otherwise
        Verify derivation of fully qualified Base64 prefix from
        inception key event dict (ked)

        Parameters:
            ked is inception key event dict
            pre is Base64 fully qualified prefix default to .qb64
        """
        try:
            dked = dict(ked)  # make copy so don't clobber original ked
            ilk = dked["t"]
            if ilk == Ilks.icp:
                labels = [key for key in dked if key not in self.IcpExcludes]
            elif ilk == Ilks.dip:
                labels = [key for key in dked if key not in self.DipExcludes]
            else:
                raise DerivationError("Invalid ilk = {} to derive prefix.".format(ilk))

            # put in dummy pre to get size correct
            dked["i"] = "{}".format(self.Dummy*CryTwoSizes[CryTwoDex.Ed25519])
            serder = Serder(ked=dked)
            dked = serder.ked  # use updated ked with valid vs element

            for l in labels:
                if l not in dked:
                    raise DerivationError("Missing element = {} from ked.".format(l))

            try:
                keys = dked["k"]
                if len(keys) != 1:
                    raise DerivationError("Basic derivation needs at most 1 key "
                                          " got {} keys instead".format(len(keys)))
                verfer = Verfer(qb64=keys[0])
            except Exception as ex:
                raise DerivationError("Error extracting public key ="
                                      " = {}".format(ex))

            if verfer.code not in [CryOneDex.Ed25519]:
                raise DerivationError("Mismatched derivation code = {}"
                                      "".format(verfer.code))

            if prefixed and ked["i"] != pre:
                return False

            cigar = Cigar(qb64=pre, verfer=verfer)

            result = cigar.verfer.verify(sig=cigar.raw, ser=serder.raw)
            return result

            #try:  # verify returns None if valid else raises ValueError
                #result = pysodium.crypto_sign_verify_detached(sig, ser, verfer.raw)
            #except Exception as ex:
                #return False

        except Exception as ex:
            return False

        return True





BASE64_PAD = b'='


# Mappings between Base64 Encode Index and Decode Characters
#  B64ChrByIdx is dict where each key is a B64 index and each value is the B64 char
#  B64IdxByChr is dict where each key is a B64 char and each value is the B64 index
# Map Base64 index to char
B64ChrByIdx = dict((index, char) for index,  char in enumerate([chr(x) for x in range(65, 91)]))
B64ChrByIdx.update([(index + 26, char) for index,  char in enumerate([chr(x) for x in range(97, 123)])])
B64ChrByIdx.update([(index + 52, char) for index,  char in enumerate([chr(x) for x in range(48, 58)])])
B64ChrByIdx[62] = '-'
B64ChrByIdx[63] = '_'

B64IdxByChr = {char: index for index, char in B64ChrByIdx.items()}  # map char to Base64 index

def IntToB64(i, l=1):
    """
    Returns conversion of int i to Base64 str

    l is min number of b64 digits padded with Base4 zeros "A"
    """
    d = deque()  # deque of characters base64
    d.appendleft(B64ChrByIdx[i % 64])
    i = i // 64
    while i:
        d.appendleft(B64ChrByIdx[i % 64])
        i = i // 64
    for j in range(l - len(d)):  # range(x)  x <= 0 means do not iterate
        d.appendleft("A")
    return ( "".join(d))

def B64ToInt(cs):
    """
    Returns conversion of Base64 str cs to int

    """
    i = 0
    for e, c in enumerate(reversed(cs)):
        i += B64IdxByChr[c] * 64 ** e
    return i


@dataclass(frozen=True)
class SigSelectCodex:
    """
    SigSelectCodex codex of selector characters for attached signature cyptographic material
    Only provide defined characters.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.
    """
    four: str = '0'  # use four character table.
    five: str = '1'  # use five character table.
    six:  str = '2'  # use six character table.
    dash: str = '-'  # use signature count table

    def __iter__(self):
        return iter(astuple(self))

SigSelDex = SigSelectCodex()  # Make instance



@dataclass(frozen=True)
class SigCntCodex:
    """
    SigCntCodex codex of four character length derivation codes that indicate
    count (number) of attached signatures following an event .
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.
    .raw is empty

    Note binary length of everything in SigCntCodex results in 0 Base64 pad bytes.

    First two code characters select format of attached signatures
    Next two code charaters select count total of attached signatures to an event
    Only provide first two characters here
    """
    Base64: str =  '-A'  # Fully Qualified Base64 Format Signatures.
    Base2:  str =  '-B'  # Fully Qualified Base2 Format Signatures.

    def __iter__(self):
        return iter(astuple(self))

SigCntDex = SigCntCodex()  #  Make instance

# Mapping of Code to Size
# Total size  qb64
SigCntSizes = {
                "-A": 4,
                "-B": 4,
              }

# size of index portion of code qb64
SigCntIdxSizes = {
                   "-A": 2,
                   "-B": 2,
                 }

# total size of raw unqualified
SigCntRawSizes = {
                   "-A": 0,
                   "-B": 0,
                 }

SIGCNTMAX = 4095  # maximum count value given two base 64 digits


@dataclass(frozen=True)
class SigTwoCodex:
    """
    SigTwoCodex codex of two character length derivation codes for attached signatures
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.

    Note binary length of everything in SigTwoCodex results in 2 Base64 pad bytes.

    First code character selects signature cipher suite
    Second code charater selects index into current signing key list
    Only provide first character here
    """
    Ed25519: str =  'A'  # Ed25519 signature.
    ECDSA_256k1: str = 'B'  # ECDSA secp256k1 signature.


    def __iter__(self):
        return iter(astuple(self))

SigTwoDex = SigTwoCodex()  #  Make instance

# Mapping of Code to Size
SigTwoSizes = {
                "A": 88,
                "B": 88,
              }

# size of index portion of code qb64
SigTwoIdxSizes = {
                   "A": 1,
                   "B": 1,
                 }

SigTwoRawSizes = {
                "A": 64,
                "B": 64,
              }


SIGTWOMAX = 63  # maximum index value given one base64 digit

@dataclass(frozen=True)
class SigFourCodex:
    """
    SigFourCodex codex of four character length derivation codes
    Only provide defined codes.
    Undefined are left out so that inclusion(exclusion) via 'in' operator works.

    Note binary length of everything in SigFourCodex results in 0 Base64 pad bytes.

    First two code characters select signature cipher suite
    Next two code charaters select index into current signing key list
    Only provide first two characters here
    """
    Ed448: str =  '0A'  # Ed448 signature.

    def __iter__(self):
        return iter(astuple(self))

SigFourDex = SigFourCodex()  #  Make instance

# Mapping of Code to Size
SigFourSizes = {
                "0A": 156,
               }

# size of index portion of code qb64
SigFourIdxSizes = {
                   "0A": 2,
                 }

SigFourRawSizes = {
                "0A": 114,
               }


SIGFOURMAX = 4095  # maximum index value given two base 64 digits

@dataclass(frozen=True)
class SigFiveCodex:
    """
    Five codex of five character length derivation codes
    Only provide defined codes. Undefined are left out so that inclusion
    exclusion via 'in' operator works.

    Note binary length of everything in Four results in 0 Base64 pad bytes.

    First three code characters select signature cipher suite
    Next two code charaters select index into current signing key list
    Only provide first three characters here
    """
    def __iter__(self):
        return iter(astuple(self))

SigFiveDex = SigFiveCodex()  #  Make instance


# Mapping of Code to Size
SigFiveSizes = {}
SigFiveIdxSizes = {}
SigFiveRawSizes = {}

SIGFIVEMAX = 4095  # maximum index value given two base 64 digits

# all sizes in one dict
SigSizes = dict(SigCntSizes)
SigSizes.update(SigTwoSizes)
SigSizes.update(SigFourSizes)
SigSizes.update(SigFiveSizes)

MINSIGSIZE = min(SigSizes.values())

SigIdxSizes = dict(SigCntIdxSizes)
SigIdxSizes.update(SigTwoIdxSizes)
SigIdxSizes.update(SigFourIdxSizes)
SigIdxSizes.update(SigFiveIdxSizes)

SigRawSizes = dict(SigCntRawSizes)
SigRawSizes.update(SigTwoRawSizes)
SigRawSizes.update(SigFourRawSizes)
SigRawSizes.update(SigFiveRawSizes)


class SigMat:
    """
    SigMat is fully qualified attached signature crypto material base class
    Sub classes are derivation code specific.

    Includes the following attributes and properites.

    Attributes:

    Properties:
        .code  str derivation code of cipher suite for signature
        .index int zero based offset into signing key list
               or if from SigCntDex then its count of attached signatures
        .raw   bytes crypto material only without code
        .pad  int number of pad chars given .raw
        .qb64 str in Base64 fully qualified with derivation code and signature crypto material
        .qb64b bytes in Base64 fully qualified with derivation code and signature crypto material
        .qb2  bytes in binary fully qualified with derivation code and signature crypto material
    """
    def __init__(self, raw=None, qb64b=None, qb64=None, qb2=None,
                 code=SigTwoDex.Ed25519, index=0):
        """
        Validate as fully qualified
        Parameters:
            raw is bytes of unqualified crypto material usable for crypto operations
            qb64b is bytes of fully qualified crypto material
            qb64 is str or bytes of fully qualified crypto material
            qb2 is bytes of fully qualified crypto material
            code is str of derivation code cipher suite
            index is int of offset index into current signing key list
                   or if from SigCntDex then its count of attached signatures

        When raw provided then validate that code is correct for length of raw
            and assign .raw .code and .index
        Else when either qb64 or qb2 provided then extract and assign .raw and .code

        """
        if raw is not None:  #  raw provided
            if not isinstance(raw, (bytes, bytearray)):
                raise TypeError("Not a bytes or bytearray, raw={}.".format(raw))
            pad = self._pad(raw)
            if (not ( (pad == 2 and (code in SigTwoDex)) or  # Two or Six or Ten
                      (pad == 0 and (code in SigCntDex)) or  # Cnt (Count)
                      (pad == 0 and (code in SigFourDex)) or  # Four or Eight
                      (pad == 1 and (code in SigFiveDex)) )):   # Five or Nine

                raise ValidationError("Wrong code={} for raw={}.".format(code, raw))

            if ( (code in SigTwoDex and ((index < 0) or (index > SIGTWOMAX)) ) or
                 (code in SigCntDex and ((index < 0) or (index > SIGFOURMAX)) ) or
                 (code in SigFourDex and ((index < 0) or (index > SIGFOURMAX)) ) or
                 (code in SigFiveDex and ((index < 0) or (index > SIGFIVEMAX)) ) ):

                raise ValidationError("Invalid index={} for code={}.".format(index, code))

            raw = raw[:SigRawSizes[code]]  # allows longer by truncating stream
            if len(raw) != SigRawSizes[code]:  # forbids shorter
                raise ValidationError("Unexpected raw size={} for code={}"
                                      " not size={}.".format(len(raw),
                                                             code,
                                                             SigRawSizes[code]))

            self._code = code  # front part without index
            self._index = index
            self._raw = bytes(raw)  # crypto ops require bytes not bytearray

        elif qb64b is not None:
            self._exfil(qb64b)

        elif qb64 is not None:
            if hasattr(qb64, "encode"):  #  ._exfil expects bytes not str
                qb64 = qb64.encode("utf-8")  #  greedy so do not use on stream
            self._exfil(qb64)

        elif qb2 is not None:  # rewrite to use direct binary exfiltration
            self._exfil(encodeB64(qb2))

        else:
            raise EmptyMaterialError("Improper initialization need raw or b64 or b2.")


    @staticmethod
    def _pad(raw):
        """
        Returns number of pad characters that would result from converting raw
        to Base64 encoding
        raw is bytes or bytearray
        """
        m = len(raw) % 3
        return (3 - m if m else 0)


    @property
    def pad(self):
        """
        Returns number of pad characters that would result from converting
        self.raw to Base64 encoding
        self.raw is raw is bytes or bytearray
        """
        return self._pad(self._raw)


    @property
    def code(self):
        """
        Returns ._code
        Makes .code read only
        """
        return self._code


    @property
    def index(self):
        """
        Returns ._index
        Makes .index read only
        """
        return self._index


    @property
    def raw(self):
        """
        Returns ._raw
        Makes .raw read only
        """
        return self._raw


    def _infil(self):
        """
        Returns fully qualified attached sig base64 bytes computed from
        self.raw, self.code and self.index.
        """
        l = SigIdxSizes[self._code]  # index length b64 characters
        # full is pre code + index
        full =  "{}{}".format(self._code, IntToB64(self._index, l=l))

        pad = self.pad
        # valid pad for code length
        if len(full) % 4 != pad:  # pad is not remainder of len(code) % 4
            raise ValidationError("Invalid code + index = {} for converted raw pad = {}."
                                  .format(full, self.pad))
        # prepending full derivation code with index and strip off trailing pad characters
        return (full.encode("utf-8") + encodeB64(self._raw)[:-pad])


    def _exfil(self, qb64b):
        """
        Extracts self.code,self.index, and self.raw from qualified base64 qb64
        """
        if len(qb64b) < MINSIGSIZE:  # Need more bytes
            raise ShortageError("Need more bytes.")

        cs = 1  # code size  initially 1 to extract selector or one char code
        code = qb64b[:cs].decode("utf-8")  # get front code, convert to str
        if hasattr(code, "decode"):  # converts bytes like to str
            code = code.decode("utf-8")
        index = 0

        # need to map code to length so can only consume proper number of chars
        # from front of qb64 so can use with full identifiers not just prefixes

        if code in SigTwoDex:  # 2 char = 1 code + 1 index
            qb64b = qb64b[:SigTwoSizes[code]]  # strip of full sigmat
            cs += 1
            index = B64IdxByChr[qb64b[cs-1:cs].decode("utf-8")]  # one character for index

        elif code == SigSelDex.four:  #  '0'
            cs += 1
            code = qb64b[0:cs].decode("utf-8")  # get front code, convert to str
            if code not in SigFourDex:  # 4 char = 2 code + 2 index
                raise ValidationError("Invalid derivation code = {} in {}.".format(code, qb64b))
            qb64b = qb64b[:SigFourSizes[code]]  # strip of full sigmat
            cs += 2
            index = B64ToInt(qb64b[cs-2:cs].decode("utf-8"))  # two characters for index

        elif code == SigSelDex.dash:  #  '-'
            cs += 1
            code = qb64b[0:cs].decode("utf-8")  # get front code, convert to str
            if code not in SigCntDex:  # 4 char = 2 code + 2 index
                raise ValidationError("Invalid derivation code = {} in {}.".format(code, qb64b))
            qb64b = qb64b[:SigCntSizes[code]]  # strip of full sigmat
            cs += 2
            index = B64ToInt(qb64b[cs-2:cs].decode("utf-8"))  # two characters for index

        else:
            raise ValueError("Improperly coded material = {}".format(qb64b))

        if len(qb64b) != SigSizes[code]:  # not correct length
            if len(qb64b) <  SigSizes[code]:  #  need more bytes
                raise ShortageError("Need more bytes.")
            else:
                raise ValidationError("Bad qb64b size expected {}, got {} "
                                      "bytes.".format(SigSizes[code],
                                                      len(qb64b)))

        pad = cs % 4  # pad is remainder pre mod 4
        # strip off prepended code and append pad characters
        base = qb64b[cs:] + pad * BASE64_PAD
        raw = decodeB64(base)

        if len(raw) != (len(qb64b) - cs) * 3 // 4:  # exact lengths
            raise ValueError("Improperly qualified material = {}".format(qb64b))

        self._code = code
        self._index = index
        self._raw = raw


    @property
    def qb64(self):
        """
        Property qb64:
        Returns Fully Qualified Base64 Version
        Assumes self.raw and self.code are correctly populated
        """
        return self.qb64b.decode("utf-8")


    @property
    def qb64b(self):
        """
        Property qb64b:
        Returns Fully Qualified Base64 Version encoded as bytes
        Assumes self.raw and self.code are correctly populated
        """
        return self._infil()


    @property
    def qb2(self):
        """
        Property qb2:
        Returns Fully Qualified Binary Version
        redo to use b64 to binary decode table since faster
        """
        # rewrite to do direct binary infiltration by
        # decode self.code as bits and prepend to self.raw
        return decodeB64(self._infil())


class SigCounter(SigMat):
    """
    SigCounter is subclass of SigMat, indexed signature material,
    That provides count of following number of attached signatures.
    Useful when parsing attached signatures from stream where SigCounter
    instance qb64 is inserted after Serder of event and before attached signatures.

    Changes default initialization code = SigCntDex.Base64
    Raises error on init if code not in SigCntDex

    See SigMat for inherited attributes and properties:

    Attributes:

    Properties:
        .count is int count of attached signatures (same as .index)

    Methods:


    """
    def __init__(self, raw=None, qb64b =None, qb64=None, qb2=None,
                 code=SigCntDex.Base64, index=None, count=None, **kwa):
        """

        Parameters:  See CryMat for inherted parameters
            count is int number of attached sigantures same as index

        """
        raw = b'' if raw is not None else raw  # force raw to be empty is

        if raw is None and qb64b is None and qb64 is None and qb2 is None:
            raw = b''

        # accept either index or count to init index
        if count is not None:
            index = count
        if index is None:
            index = 1  # most common case

        # force raw empty
        super(SigCounter, self).__init__(raw=raw, qb64b=qb64b, qb64=qb64, qb2=qb2,
                                         code=code, index=index, **kwa)

        if self.code not in SigCntDex:
            raise ValidationError("Invalid code = {} for SigCounter."
                                  "".format(self.code))

    @property
    def count(self):
        """
        Property counter:
        Returns .index as count
        Assumes ._index is correctly assigned
        """
        return self.index


class Siger(SigMat):
    """
    Siger is subclass of SigMat, indexed signature material,
    Adds .verfer property which is instance of Verfer that provides
          associated signature verifier.

    See SigMat for inherited attributes and properties:

    Attributes:

    Properties:
        .verfer is Verfer object instance

    Methods:


    """
    def __init__(self, verfer=None, **kwa):
        """
        Assign verfer to ._verfer

        Parameters:  See CryMat for inherted parameters
            verfer if Verfer instance if any

        """
        super(Siger, self).__init__(**kwa)

        self._verfer = verfer

    @property
    def verfer(self):
        """
        Property verfer:
        Returns Verfer instance
        Assumes ._verfer is correctly assigned
        """
        return self._verfer

    @verfer.setter
    def verfer(self, verfer):
        """ verfer property setter """
        self._verfer = verfer



class Serder:
    """
    Serder is KERI key event serializer-deserializer class
    Only supports current version VERSION

    Has the following public properties:

    Properties:
        .raw is bytes of serialized event only
        .ked is key event dict
        .kind is serialization kind string value (see namedtuple coring.Serials)
        .version is Versionage instance of event version
        .size is int of number of bytes in serialed event only
        .diger is Diger instance of digest of .raw
        .dig  is qb64 digest from .diger
        .digb is qb64b digest from .diger
        .verfers is list of Verfers converted from .ked["k"]
        .sn is int sequence number converted from .ked["s"]
        .pre is qb64 str of identifier prefix from .ked["i"]
        .preb is qb64b bytes of identifier prefix from .ked["i"]

    Hidden Attributes:
          ._raw is bytes of serialized event only
          ._ked is key event dict
          ._kind is serialization kind string value (see namedtuple coring.Serials)
            supported kinds are 'json', 'cbor', 'msgpack', 'binary'
          ._version is Versionage instance of event version
          ._size is int of number of bytes in serialed event only
          ._code is default code for .diger
          ._diger is Diger instance of digest of .raw

    Note:
        loads and jumps of json use str whereas cbor and msgpack use bytes

    """
    def __init__(self, raw=b'', ked=None, kind=None, code=CryOneDex.Blake3_256):
        """
        Deserialize if raw provided
        Serialize if ked provided but not raw
        When serilaizing if kind provided then use kind instead of field in ked

        Parameters:
          raw is bytes of serialized event plus any attached signatures
          ked is key event dict or None
            if None its deserialized from raw
          kind is serialization kind string value or None (see namedtuple coring.Serials)
            supported kinds are 'json', 'cbor', 'msgpack', 'binary'
            if kind is None then its extracted from ked or raw
          code is .diger default digest code

        """
        self._code = code  # need default code for .diger
        if raw:  # deserialize raw using property
            self.raw = raw  # raw property setter does the deserialization
        elif ked: # serialize ked
            self._kind = kind
            self.ked = ked  # ked property setter does the serialization
        else:
            raise ValueError("Improper initialization need raw or ked.")


    @staticmethod
    def _sniff(raw):
        """
        Returns serialization kind, version and size from serialized event raw
        by investigating leading bytes that contain version string

        Parameters:
          raw is bytes of serialized event

        """
        if len(raw) < MINSNIFFSIZE:
            raise ShortageError("Need more bytes.")

        match = Rever.search(raw)  #  Rever's regex takes bytes
        if not match or match.start() > 12:
            raise ValueError("Invalid version string in raw = {}".format(raw))

        major, minor, kind, size = match.group("major", "minor", "kind", "size")
        version = Versionage(major=int(major, 16), minor=int(minor, 16))
        kind = kind.decode("utf-8")
        if kind not in Serials:
            raise ValueError("Invalid serialization kind = {}".format(kind))
        size = int(size, 16)
        return(kind, version, size)


    def _inhale(self, raw):
        """
        Parses serilized event ser of serialization kind and assigns to
        instance attributes.

        Parameters:
          raw is bytes of serialized event
          kind is str of raw serialization kind (see namedtuple Serials)
          size is int size of raw to be deserialized

        Note:
          loads and jumps of json use str whereas cbor and msgpack use bytes

        """
        kind, version, size = self._sniff(raw)
        if version != Version:
            raise VersionError("Unsupported version = {}.{}".format(version.major,
                                                                    version.minor))

        if len(raw) < size:
            raise ShortageError("Need more bytes.")

        if kind == Serials.json:
            try:
                ked = json.loads(raw[:size].decode("utf-8"))
            except Exception as ex:
                raise ex

        elif kind == Serials.mgpk:
            try:
                ked = msgpack.loads(raw[:size])
            except Exception as ex:
                raise ex

        elif kind ==  Serials.cbor:
            try:
                ked = cbor.loads(raw[:size])
            except Exception as ex:
                raise ex

        else:
            ked = None

        return (ked, kind, version, size)


    def _exhale(self, ked,  kind=None):
        """
        ked is key event dict
        kind is serialization if given else use one given in ked
        Returns tuple of (raw, kind, ked, version) where:
            raw is serialized event as bytes of kind
            kind is serialzation kind
            ked is key event dict
            version is Versionage instance

        Assumes only supports Version
        """
        if "v" not in ked:
            raise ValueError("Missing or empty version string in key event dict = {}".format(ked))

        knd, version, size = Deversify(ked["v"])  # extract kind and version
        if version != Version:
            raise VersionError("Unsupported version = {}.{}".format(version.major,
                                                                    version.minor))

        if not kind:
            kind = knd

        if kind not in Serials:
            raise ValueError("Invalid serialization kind = {}".format(kind))

        if kind == Serials.json:
            raw = json.dumps(ked, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        elif kind == Serials.mgpk:
            raw = msgpack.dumps(ked)

        elif kind == Serials.cbor:
            raw = cbor.dumps(ked)

        else:
            raise ValueError("Invalid serialization kind = {}".format(kind))

        size = len(raw)

        match = Rever.search(raw)  #  Rever's regex takes bytes
        if not match or match.start() > 12:
            raise ValueError("Invalid version string in raw = {}".format(raw))

        fore, back = match.span()  #  full version string
        # update vs with latest kind version size
        vs = Versify(version=version, kind=kind, size=size)
        # replace old version string in raw with new one
        raw = b'%b%b%b' % (raw[:fore], vs.encode("utf-8"), raw[back:])
        if size != len(raw):  # substitution messed up
            raise ValueError("Malformed version string size = {}".format(vs))
        ked["v"] = vs  #  update ked

        return (raw, kind, ked, version)


    def compare(self, dig=None, diger=None):
        """
        Returns True  if dig and either .diger.qb64 or .diger.qb64b match or
            if both .diger.raw and dig are valid digests of self.raw
            Otherwise returns False

        Convenience method to allow comparison of own .diger digest self.raw
        with some other purported digest of self.raw

        Parameters:
            dig is qb64b or qb64 digest of ser to compare with .diger.raw
            diger is Diger instance of digest of ser to compare with .diger.raw

            if both supplied dig takes precedence


        If both match then as optimization returns True and does not verify either
          as digest of ser
        If both have same code but do not match then as optimization returns False
           and does not verify if either is digest of ser
        But if both do not match then recalcs both digests to verify they
        they are both digests of ser with or without matching codes.
        """
        return (self.diger.compare(ser=self.raw, dig=dig, diger=diger))


    @property
    def raw(self):
        """ raw property getter """
        return self._raw


    @raw.setter
    def raw(self, raw):
        """ raw property setter """
        ked, kind, version, size = self._inhale(raw=raw)
        self._raw = bytes(raw[:size])  # crypto ops require bytes not bytearray
        self._ked = ked
        self._kind = kind
        self._version = version
        self._size = size
        self._diger = Diger(ser=self._raw, code=self._code)


    @property
    def ked(self):
        """ ked property getter"""
        return self._ked


    @ked.setter
    def ked(self, ked):
        """ ked property setter  assumes ._kind """
        raw, kind, ked, version = self._exhale(ked=ked, kind=self._kind)
        size = len(raw)
        self._raw = raw[:size]
        self._ked = ked
        self._kind = kind
        self._size = size
        self._version = version
        self._diger = Diger(ser=self._raw, code=self._code)


    @property
    def kind(self):
        """ kind property getter"""
        return self._kind


    @kind.setter
    def kind(self, kind):
        """ kind property setter Assumes ._ked """
        raw, kind, ked, version = self._exhale(ked=self._ked, kind=kind)
        size = len(raw)
        self._raw = raw[:size]
        self._ked = ked
        self._kind = kind
        self._size = size
        self._version = version
        self._diger = Diger(ser=self._raw, code=self._code)


    @property
    def version(self):
        """ version property getter"""
        return self._version


    @property
    def size(self):
        """ size property getter"""
        return self._size


    @property
    def diger(self):
        """
        Returns Diger of digest of self.raw
        diger (digest material) property getter
        """
        return self._diger


    @property
    def dig(self):
        """
        Returns qualified Base64 digest of self.raw
        dig (digest) property getter
        """
        return self.diger.qb64


    @property
    def digb(self):
        """
        Returns qualified Base64 digest of self.raw
        dig (digest) property getter
        """
        return self.diger.qb64b


    @property
    def verfers(self):
        """
        Returns list of Verifier instances as converted from .ked.keys
        verfers property getter
        """
        if "k" in self.ked:  # establishment event
            keys = self.ked["k"]
        else:  # non-establishment event
            keys =  []

        return [Verfer(qb64=key) for key in keys]

    @property
    def sn(self):
        """
        Returns int of .ked["s"] (sequence number)
        sn (sequence number) property getter
        """
        return int(self.ked["s"], 16)


    @property
    def pre(self):
        """
        Returns str qb64  of .ked["i"] (identifier prefix)
        pre (identifier prefix) property getter
        """
        return self.ked["i"]


    @property
    def preb(self):
        """
        Returns bytes qb64b  of .ked["i"] (identifier prefix)
        preb (identifier prefix) property getter
        """
        return self.pre.encode("utf-8")



class Tholder:
    """
    Tholder is KERI Signing Threshold Satisfactionclass
    .satisfy method evaluates satisfaction based on ordered list of indices of
    verified signatures where indices correspond to offsets in key list of
    associated signatures.

    Has the following public properties:

    Properties:
        .sith is original signing threshold
        .thold is parsed signing threshold
        .limen is the extracted string for the next commitment to the threshold
        .weighted is Boolean True if fractional weighted threshold False if numeric
        .size is int of minimun size of keys list

    Hidden:
        ._sith is original signing threshold
        ._thold is parsed signing threshold
        ._limen is extracted string for the next commitment to threshold
        ._weighted is Boolean, True if fractional weighted threshold False if numeric
        ._size is int minimum size of of keys list
        ._satisfy is method reference of threshold specified verification method
        ._satisfy_numeric is numeric threshold verification method
        ._satisfy_weighted is fractional weighted threshold verification method


    """
    def __init__(self, sith=''):
        """
        Parse threshold

        Parameters:
            sith is either hex string of threshold number or iterable of fractional
                weights. Fractional weights may be either an iterable of
                fraction strings or an iterable of iterables of fractions strings.

                The verify method appropriately evaluates each of the threshold
                forms.

        """
        self._sith = sith
        if isinstance(sith, str):
            self._weighted = False
            thold = int(sith, 16)
            if thold < 1:
                raise ValueError("Invalid sith = {} < 1.".format(thold))
            self._thold = thold
            self._size = self._thold  # used to verify that keys list size is at least size
            self._satisfy = self._satisfy_numeric
            self._limen = self._sith  # just use hex string

        else:  # assumes iterable of weights or iterable of iterables of weights
            self._weighted = True
            if not sith:  # empty iterable
                raise ValueError("Invalid sith = {}, empty weight list.".format(sith))

            mask = [isinstance(w, str) for w in sith]
            if mask and all(mask):  # not empty and all strings
                sith = [sith]  # make list of list so uniform
            elif any(mask):  # some strings but not all
                raise ValueError("Invalid sith = {} some weights non non string."
                                 "".format(sith))

            # replace fractional strings with fractions
            thold = []
            for clause in sith:  # convert string fractions to Fractions
                thold.append([Fraction(w) for w in clause])  # append list of Fractions

            for clause in thold:  #  sum of fractions in clause must be >= 1
                if not (sum(clause) >= 1):
                    raise ValueError("Invalid sith cLause = {}, all clause weight "
                                     "sums must be >= 1.".format(thold))

            self._thold = thold
            self._size = sum(len(clause) for clause in thold)
            self._satisfy = self._satisfy_weighted

            # extract limen from sith
            self._limen = "&".join([",".join(clause) for clause in sith])



    @property
    def sith(self):
        """ sith property getter """
        return self._sith

    @property
    def thold(self):
        """ thold property getter """
        return self._thold

    @property
    def weighted(self):
        """ weighted property getter """
        return self._weighted

    @property
    def size(self):
        """ size property getter """
        return self._size

    @property
    def limen(self):
        """ limen property getter """
        return self._limen


    def satisfy(self, indices):
        """
        Returns True if indices list of verified signature key indices satisfies
        threshold, False otherwise.

        Parameters:
            indices is list of indices (offsets into key list) of verified signatures
        """
        return (self._satisfy(indices=indices))


    def _satisfy_numeric(self, indices):
        """
        Returns True if satisfies numeric threshold False otherwise

        Parameters:
            indices is list of indices (offsets into key list) of verified signatures
        """
        try:
            if len(indices) >= self.thold:
                return True

        except Exception as ex:
            return False

        return False


    def _satisfy_weighted(self, indices):
        """
        Returns True if satifies fractional weighted threshold False otherwise


        Parameters:
            indices is list of indices (offsets into key list) of verified signatures

        """
        try:
            if not indices:  #  empty indices
                return False

            # remove duplicates with set, sort low to high
            indices = sorted(set(indices))
            sats = [False] * self.size  # default all satifactions to False
            for idx in indices:
                sats[idx] = True  # set aat atverified signature index to True

            wio = 0  # weight index offset
            for clause in self.thold:
                cw = 0  # init clause weight
                for w in clause:
                    if sats[wio]:  # verified signature so weight applies
                        cw += w
                    wio += 1
                if cw < 1:
                    return False

            return True  # all clauses including final one cw >= 1

        except Exception as ex:
            return False

        return False

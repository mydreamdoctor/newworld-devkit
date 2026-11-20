/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 */

#pragma once

#include <AzCore/Module/Module.h>

namespace NWLighting
{
    class NWLightingModule : public AZ::Module
    {
    public:
        AZ_RTTI(NWLightingModule, "{6A1F2B7C-3D4E-4F50-8A61-72B3C4D5E6F7}", AZ::Module);
        AZ_CLASS_ALLOCATOR(NWLightingModule, AZ::SystemAllocator);

        NWLightingModule();

        AZ::ComponentTypeList GetRequiredSystemComponents() const override;
    };
} // namespace NWLighting
